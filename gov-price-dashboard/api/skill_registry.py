"""
Skill 注册中心 - 扫 ~/.openclaw/workspace/skills/*/skill.yml
所有 dashboard 动态行为（ALL_INDICES / 城市清单 / sync-progress 配置）都从这里读。

设计原则：
- 单例缓存 + 显式 reload()，避免每次请求都扫盘
- 找不到 skill.yml 的目录自动跳过（gov-price-dashboard 自身、gov-price-etl 等）
- config_path 可选指向 skill 的 config.yml，用于动态读 cities / last_period
"""
from __future__ import annotations
import os
import glob
import logging
from pathlib import Path
from typing import Optional

import yaml

log = logging.getLogger("skill_registry")


def _resolve_skills_root() -> str:
    """解析 SKILLS_ROOT 扫描根目录。

    优先级：
      1) 环境变量 SKILLS_ROOT（部署/调试可显式覆盖）
      2) 自动从本文件路径反推：
         <skills>/gov-price-dashboard/api/skill_registry.py 的 parents[2]
         就是 <skills> 根目录。这样无论 workspace 叫 cjt 还是别的，
         都能定位到正确的 skills/，不依赖硬编码的 workspace 名。
    """
    env_root = os.environ.get("SKILLS_ROOT")
    if env_root:
        return env_root
    # 本文件路径：<skills>/gov-price-dashboard/api/skill_registry.py
    # parents[2] 即 <skills>
    return str(Path(__file__).resolve().parents[2])


SKILLS_ROOT = _resolve_skills_root()

# 必须排除的目录（这些不是抓取 skill）
EXCLUDE_DIRS = {
    "gov-price-dashboard",
    "gov-price-etl",
    "self-improving-agent",
    "feishu",
}

# 模块级缓存
_cache: Optional[list[dict]] = None
_index: dict[str, dict] = {}


def _read_yaml(path: Path) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else None
    except Exception as e:
        log.warning("解析 %s 失败: %s", path, e)
        return None


def _read_cities_from_config(skill_dir_name: str, config_path: str) -> Optional[list[str]]:
    """从 skill 的 config.yml 里读 cities/site.counties 列表（如果存在）"""
    if not config_path:
        return None
    # 优先按 skill_dir_name 拼接，再 fallback 原始路径
    candidates = [
        Path(SKILLS_ROOT) / skill_dir_name / "config.yml",
        Path(config_path),
    ]
    for p in candidates:
        if p.exists():
            cfg = _read_yaml(p)
            if not cfg:
                continue
            cities = cfg.get("cities")
            if isinstance(cities, list):
                return [str(c) for c in cities]
            site = cfg.get("site", {}) or {}
            counties = site.get("counties")
            if isinstance(counties, list):
                return [str(c) for c in counties]
    return None


def _read_site_url_from_config(skill_dir_name: str, config_path: str) -> Optional[str]:
    """从 skill 的 config.yml 里读抓取入口 URL（供 dashboard 卡片回溯）。

    拼接优先级（与 sync.py 实际抓取 URL 对齐）：
      1) site.url                     — 重庆、四川等直接给完整 URL 的
      2) base_url + list_page_pattern.format(n=1)
                                       — 海南、湖南、宁夏、青海多页型
      3) base_url + list_path         — 河南、呼和浩特、江西、青岛、威海、陕西
      4) site.price_page              — 日照 SPA 入口特殊情况
      5) site.base_url                — 吉林、西安、菏泽、济南、新疆（入口本身完整）
    返回 None 表示无原网址可回溯。
    """
    if not config_path:
        config_path = "config.yml"
    candidates = [
        Path(SKILLS_ROOT) / skill_dir_name / config_path,
        Path(SKILLS_ROOT) / skill_dir_name / "config.yml",
        Path(config_path),
    ]
    for p in candidates:
        if not p.exists():
            continue
        cfg = _read_yaml(p)
        if not cfg:
            continue
        site = cfg.get("site", {}) or {}
        # 1) 直接给的完整 URL
        url = site.get("url")
        if isinstance(url, str) and url.strip():
            return url.strip()
        base = site.get("base_url")
        if not isinstance(base, str) or not base.strip():
            continue
        base = base.rstrip("/")
        # 2) 多页型拼第 1 页
        pattern = site.get("list_page_pattern")
        if isinstance(pattern, str) and pattern.strip():
            path = pattern
            for token, val in (("{n}", "1"), ("{page}", "1"), ("{p}", "1")):
                path = path.replace(token, val)
            return base + path
        # 3) 静态 list_path（部分含页位符）
        list_path = site.get("list_path")
        if isinstance(list_path, str) and list_path.strip():
            path = list_path
            for token, val in (("{n}", "1"), ("{page}", "1"), ("{p}", "1")):
                path = path.replace(token, val)
            return base + path
        # 4) SPA 型（rizhao 的 price_page）
        price_page = site.get("price_page")
        if isinstance(price_page, str) and price_page.strip():
            return price_page.strip()
        # 5) base_url 本身已是完整入口（jilin/xian/heze/jinan/xinjiang）
        return base
    return None


def _discover() -> list[dict]:
    """扫描所有 skill 目录，返回注册清单"""
    if not os.path.isdir(SKILLS_ROOT):
        log.warning("SKILLS_ROOT 不存在: %s", SKILLS_ROOT)
        return []

    skills: list[dict] = []
    for skill_dir in sorted(os.listdir(SKILLS_ROOT)):
        if skill_dir in EXCLUDE_DIRS or skill_dir.startswith("."):
            continue
        yml_path = Path(SKILLS_ROOT) / skill_dir / "skill.yml"
        if not yml_path.exists():
            continue
        data = _read_yaml(yml_path)
        if not data:
            continue
        key = data.get("key")
        if not key:
            log.warning("%s 缺 key 字段，跳过", yml_path)
            continue
        # 补默认值
        data.setdefault("label", key)
        data.setdefault("skill_dir", skill_dir)
        # 推断默认 dwd_index（dwd_<key>_price 约定），yml 写了就以 yml 为准
        if not data.get("dwd_index"):
            data["dwd_index"] = f"dwd_{key}_price"
        # 推断默认 progress_mode（county | period | catalogue）
        data.setdefault("progress_mode", "county")
        # 推断默认 expand_label（前端 ScrapeView 展开按钮文案）
        mode = data.get("progress_mode")
        if not data.get("expand_label"):
            if mode == "period":
                data["expand_label"] = "▾ 期数详情"
            elif mode == "catalogue":
                data["expand_label"] = "▾ 分类详情"
            else:  # county
                data["expand_label"] = "▾ 区县记录"
        # 推断默认 county_field（county 模式用：current_county | area | county）
        if mode == "county" and not data.get("county_field"):
            # 约定：xian 用 current_county，其余 city（chongqing）默认 area
            data["county_field"] = "current_county" if key == "xian" else "area"
        # 推断默认 catalogue_field（catalogue 模式用：area | catalogue | tab_type）
        if mode == "catalogue" and not data.get("catalogue_field"):
            default_cat_field = {
                "sichuan": "area",
                "jinan": "catalogue",
                "rizhao": "tab_type",
            }.get(key, "catalogue")
            data["catalogue_field"] = default_cat_field
        # 若 yml 没写 cities，尝试从 config.yml 读
        if not data.get("cities"):
            cfg_cities = _read_cities_from_config(
                skill_dir, data.get("config_path", "")
            )
            if cfg_cities:
                data["cities"] = cfg_cities
        # 从 config.yml 读原网址（dashboard 卡片回溯入口）
        # yml 显式写了 site_url 就以 yml 为准，否则从 config.yml 推
        if not data.get("site_url"):
            cfg_url = _read_site_url_from_config(
                skill_dir, data.get("config_path", "")
            )
            if cfg_url:
                data["site_url"] = cfg_url
        # 把 config_path 标准化为绝对路径（基于 SKILLS_ROOT + skill_dir，避免后端进程在不同 cwd 下打不开）
        cfg_path = data.get("config_path")
        if cfg_path:
            if not os.path.isabs(cfg_path):
                cfg_path = str(Path(SKILLS_ROOT) / skill_dir / cfg_path)
            data["config_path"] = cfg_path
        skills.append(data)

    log.info("发现 %d 个 skill: %s", len(skills), [s["key"] for s in skills])
    return skills


def reload() -> list[dict]:
    """强制重新扫描，返回最新清单"""
    global _cache, _index
    _cache = _discover()
    _index = {s["key"]: s for s in _cache}
    return _cache


def get_all() -> list[dict]:
    """获取全部已注册 skill（首次调用时懒加载）"""
    if _cache is None:
        reload()
    return list(_cache or [])


def get(key: str) -> Optional[dict]:
    """按 key 查单个 skill 配置"""
    if not _index:
        reload()
    return _index.get(key)


def all_dws_indices() -> list[str]:
    """返回所有 skill 的 dws_index（去重，过滤空值）"""
    seen: set[str] = set()
    out: list[str] = []
    for s in get_all():
        idx = s.get("dws_index")
        if idx and idx not in seen:
            seen.add(idx)
            out.append(idx)
    return out


def dws_indices_csv() -> str:
    """逗号分隔形式，给 es.search(index=...) 用"""
    return ",".join(all_dws_indices())


def all_ods_indices() -> list[str]:
    """返回所有 skill 的 ods_index（去重，过滤空值）"""
    seen: set[str] = set()
    out: list[str] = []
    for s in get_all():
        idx = s.get("ods_index")
        if idx and idx not in seen:
            seen.add(idx)
            out.append(idx)
    return out


def ods_indices_csv() -> str:
    """逗号分隔形式，给 es.search(index=...) 用"""
    return ",".join(all_ods_indices())


def all_dwd_indices() -> list[str]:
    """返回所有 skill 的 dwd_index（去重，过滤空值）"""
    seen: set[str] = set()
    out: list[str] = []
    for s in get_all():
        idx = s.get("dwd_index")
        if idx and idx not in seen:
            seen.add(idx)
            out.append(idx)
    return out


def dwd_indices_csv() -> str:
    """逗号分隔形式，给 es.search(index=...) 用"""
    return ",".join(all_dwd_indices())


def all_dws_indices_for_dashboard() -> list[dict]:
    """返回 dashboard 用的 dws city config（{key, dws, ods, dwd, label, ...}）"""
    out = []
    for s in get_all():
        out.append({
            "key": s["key"],
            "label": s.get("label", s["key"]),
            "ods": s.get("ods_index"),
            "dwd": s.get("dwd_index"),
            "dws": s.get("dws_index"),
            "progress_index": s.get("progress_index"),
            "progress_mode": s.get("progress_mode"),
            "county_field": s.get("county_field"),
            "catalogue_field": s.get("catalogue_field"),
            "skill_dir": s.get("skill_dir"),
            "cities": s.get("cities", []),
            "site_url": s.get("site_url"),  # 数据源入口 URL，dashboard 卡片回溯用
        })
    return out


if __name__ == "__main__":
    # 调试用：python -m api.skill_registry
    import json
    print(json.dumps(get_all(), ensure_ascii=False, indent=2))

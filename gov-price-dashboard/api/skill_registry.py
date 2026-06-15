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

# 默认扫描根目录（可用 SKILLS_ROOT 环境变量覆盖）
SKILLS_ROOT = os.environ.get(
    "SKILLS_ROOT",
    str(Path.home() / ".openclaw" / "workspace" / "skills"),
)

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
        # 若 yml 没写 cities，尝试从 config.yml 读
        if not data.get("cities"):
            cfg_cities = _read_cities_from_config(
                skill_dir, data.get("config_path", "")
            )
            if cfg_cities:
                data["cities"] = cfg_cities
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


if __name__ == "__main__":
    # 调试用：python -m api.skill_registry
    import json
    print(json.dumps(get_all(), ensure_ascii=False, indent=2))

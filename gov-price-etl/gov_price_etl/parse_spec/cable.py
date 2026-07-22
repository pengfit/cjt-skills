"""parse_spec/cable.py - 电力/控制电缆 GB/T 12706 + GB/T 19666 命名解析

v0.10 (2026-07-22) 新增。

问题背景：
- 旧 ETL 解析器对 spec='YJV-0.6/1kV-3*2.5mm2' 这种电缆命名识别错位，
  把 'YJV-0'（型号+电压开头）截断后当 type='YJV-0'，
  且把 '0.6'/'1kV'/'3'/'2.5' 各种数字拆给错误的字段（pressure/diameter/thickness 等）。
- NORM 层 (gov-price-normalization) 已经实现 L1 normalize_cable_type() 反解，
  但 ETL 层是数据源头，应在 ETL 就拆对，避免脏数据先入 DWS 再被 NORM 兜底。

命名结构（GB/T 12706 + GB/T 19666）：
    [阻燃/耐火前缀]-[主体型号]-[铠装代码]-[电压]-[芯数×截面]
    例：ZA-YJV22-8.7/15KV-3*50mm2
    例：WDZN-YJ(F)E-0.6/1kV-4*4
    例：KVV-450/750V-4*1.5mm2

策略：
- 与 NORM 层共用一份规则 (cable_type_rules.json)，从 monorepo data/ 加载。
- 返回字段：type / voltage / core_count / cross_section / fire_rating / armor_type
- 与基类解析器解耦：parse_cable_spec() 是纯函数，调用方可决定是否合并基类结果。

使用：
    from gov_price_etl.parse_spec.cable import parse_cable_spec, is_cable_breed

    if is_cable_breed(breed):
        attrs = parse_cable_spec(spec, breed)
        # attrs = {"type": "YJV", "voltage": "0.6/1kV", "core_count": "3",
        #          "cross_section": "2.5mm²", "fire_rating": None, "armor_type": None}
"""
from __future__ import annotations
import json
import os
import re
import threading
from pathlib import Path
from typing import Optional

# ── 规则加载（与 NORM 层共享 monorepo data/cable_type_rules.json）──────────────
_RULES_CACHE: dict = {}
_RULES_PATH_CACHE: dict = {}
_RULES_LOCK = threading.Lock()


def _load_cable_rules() -> dict:
    """懒加载 + 缓存 + mtime 失效。失败返空 dict。"""
    with _RULES_LOCK:
        try:
            from gov_price_etl.paths import DATA_DIR, ETL_PROJECT_ROOT
        except Exception:
            return {}

        candidates = [
            DATA_DIR / "cable_type_rules.json",          # monorepo 共享
            ETL_PROJECT_ROOT / "data" / "cable_type_rules.json",  # ETL 私有 fallback
        ]
        env_path = os.environ.get("GOV_PRICE_CABLE_RULES_FILE")
        if env_path:
            candidates.insert(0, Path(env_path))

        chosen = None
        for c in candidates:
            if c.exists():
                chosen = c
                break
        if chosen is None:
            return {}

        try:
            mtime = chosen.stat().st_mtime
        except Exception:
            return {}

        if (_RULES_PATH_CACHE.get("path") == chosen
                and _RULES_PATH_CACHE.get("mtime") == mtime):
            return _RULES_CACHE

        try:
            with open(chosen, encoding="utf-8") as f:
                data = json.load(f)
            _RULES_CACHE.clear()
            _RULES_CACHE.update(data)
            _RULES_PATH_CACHE["path"] = chosen
            _RULES_PATH_CACHE["mtime"] = mtime
            return data
        except Exception:
            return {}


def clear_cache() -> None:
    """测试用：清空缓存。"""
    with _RULES_LOCK:
        _RULES_CACHE.clear()
        _RULES_PATH_CACHE.clear()


# ── 公开 API ──────────────────────────────────────────────────────────────
def is_cable_breed(breed: str) -> bool:
    """breed 含电缆关键词（电力电缆 / 控制电缆 / ...）返回 True。

    复用 cable_type_rules.json 里的 cable_breed_keywords 配置。
    """
    if not breed:
        return False
    rules = _load_cable_rules()
    for kw in rules.get("cable_breed_keywords", []):
        if kw in breed:
            return True
    return False


def parse_cable_spec(spec: str, breed: str = "") -> dict:
    """GB/T 12706 命名反解，返回结构化 attr dict。

    适用条件：breed 含电缆关键词。其它 breed 应先调 is_cable_breed() 判断。

    Returns:
        {
            "type":          "YJV22",     # 主体+铠装
            "voltage":       "8.7/15kV",  # 规范化
            "core_count":    3,           # int
            "cross_section": "50mm²",     # 带单位
            "fire_rating":   "A级阻燃",   # 中文说明
            "armor_type":    "钢带铠装",  # 中文说明
        }
        或 {}（不匹配时返回空，由调用方 fallback 到基类解析器）
    """
    if not spec:
        return {}
    if not is_cable_breed(breed):
        return {}

    rules = _load_cable_rules()
    pattern = rules.get("spec_pattern")
    if not pattern:
        return {}

    m = re.match(pattern, spec, re.IGNORECASE)
    if not m:
        return {}

    g = m.groupdict()
    body = (g.get("body") or "").upper()
    armor = g.get("armor") or ""
    fire = (g.get("fire") or "").upper()
    voltage_raw = g.get("voltage") or ""
    core = int(g["core"]) if g.get("core") else None
    section = g.get("section") or ""

    # 阻燃/耐火中文说明
    fire_codes = rules.get("fire_codes", {})
    fire_rating = fire_codes.get(fire) or fire_codes.get(fire.replace("-", "")) or None
    if not fire_rating and fire:
        fire_rating = fire

    # 铠装类型中文说明
    armor_codes = rules.get("armor_codes", {})
    armor_type = armor_codes.get(armor) or None

    # 电压规范化（KV → kV）
    voltage = _canon_voltage(voltage_raw) if voltage_raw else None

    # 截面加单位
    cross_section = f"{section}mm²" if section else None

    # 主体+铠装 = type
    canonical_type = (body + armor) if armor else body

    return {
        "type": canonical_type,
        "voltage": voltage,
        "core_count": core,
        "cross_section": cross_section,
        "fire_rating": fire_rating,
        "armor_type": armor_type,
    }


def _canon_voltage(raw: str) -> str:
    """电压规范化: '0.6/1KV' → '0.6/1kV'; '450/750V' → '450/750V'。"""
    s = raw.strip()
    s = re.sub(r"(\d)KV", r"\1kV", s)
    s = re.sub(r"(^|\s)KV", r"\1kV", s)
    return s
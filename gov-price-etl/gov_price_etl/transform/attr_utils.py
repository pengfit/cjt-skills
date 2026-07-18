"""transform/attr_utils.py - attr 字段提取与转换工具

被 DWD→DWS 同步流程复用，处理四种历史遗留格式：
  1. nested attr 字段（新格式，list of {k, v}）
  2. dict attr 字段（脏数据，老 ETL 误存成单 object）
  3. attr_* 前缀字段（旧 ETL 写入）
  4. 顶层扁平字段（手动修复或历史遗留）

v0.9（2026-07-05）：在写入 DWS 前做 v 字段质量校验（sanitize_attr），
丢弃非数值/无单位/纯描述的污染值。常见案例：
  - wall_thickness='不分规格' / 'δ4' / '彩色陶瓷颗粒' / '壁厚δ'
  - core_count='多芯' / '光纤'
  - pressure='P10' / 'D400'（不该是数值压力，被错位）

color/material/grade 等自由文本字段保持原状，不受清洗影响。
"""
import re as _re

# 顶层扁平字段（出现在这些 key 名下时认为是 attr）
TOPO_FIELDS = (
    "diameter", "diameter_range",
    "thickness", "length", "width", "height",
    "material", "grade", "pressure", "color", "series",
    "temperature", "voltage", "current", "cores",
    "form", "surface", "fire_rating", "ip_rating",
    "ring_stiffness", "cross_section", "inner_diameter",
    "wall_thickness", "fiber_core", "cable_length",
    "channels", "doors", "media", "range", "output",
    "asphalt_type", "cement_content", "temp_range",
    "humidity_range", "length_range", "height_range",
    "drain_type", "inlet_type", "installation_type",
)


def build_attr(doc: dict) -> dict:
    """从 DWD 文档中提取 attr 字段（扁平 dict，仅保留非空值）。

    优先提取 nested attr 字段（新格式），同时兼容 dict attr 字段（脏数据）、
    attr_* 前缀字段和顶层扁平字段（历史遗留）。
    """
    attr = {}

    # 标准路径 1：nested attr 字段（list of {k, v}）
    nested = doc.get("attr")
    if isinstance(nested, list):
        for item in nested:
            if isinstance(item, dict):
                k = item.get("k", "")
                v = item.get("v", "")
                if k and v and str(v).lower() not in ("", "null", "none"):
                    attr[k] = str(v)
    elif isinstance(nested, dict):
        # 标准路径 1b：dict 形式的 attr（历史脏数据，mapping 设为 nested 但实际存成 object）
        for k, v in nested.items():
            if v is None:
                continue
            s = str(v).strip()
            if s and s.lower() not in ("", "null", "none"):
                attr[k] = s

    # 标准路径 2：attr_* 前缀字段
    if not attr:
        for f, v in doc.items():
            if not f.startswith("attr_"):
                continue
            if v is None:
                continue
            s = str(v).strip()
            if s and s.lower() not in ("", "null", "none"):
                attr[f[5:]] = s  # strip "attr_" (5 chars) prefix

    # 兼容路径：顶层扁平字段
    if not attr:
        for f in TOPO_FIELDS:
            v = doc.get(f)
            if v is None:
                continue
            s = str(v).strip()
            if s and s.lower() not in ("", "null", "none"):
                attr[f] = s
    return attr


# ── v0.9 attr 质量校验 ──────────────────────────────────────
# 数值型字段：值必须含至少一个阿拉伯数字，且不能纯中文
_NUMERIC_REQUIRED_DIGIT = frozenset({
    "wall_thickness", "core_count", "thickness",
    "diameter", "outer_diameter", "inner_diameter",
    "length", "width", "height", "voltage", "pressure",
    "cross_section", "ring_stiffness", "fiber_core",
    "channels", "doors", "current", "temperature", "output",
})
# 数值型字段必须含语义单位（regex 不区分大小写）
_NUMERIC_REQUIRED_UNIT = {
    "wall_thickness":  r"(?i)(?:mm|cm|μm|um|μ|inch|英寸)",
    "thickness":       r"(?i)(?:mm|cm|μm|um|μ|inch|英寸)",
    "outer_diameter":  r"(?i)(?:mm|cm|DN|^D\d+|\u03c6|\u03a6)",
    "inner_diameter":  r"(?i)(?:mm|cm|DN|^D\d+|\u03c6|\u03a6)",
    "voltage":         r"(?i)(?:V\b|KV|kV|DC|AC)",
    "pressure":        r"(?i)(?:MPa|PN|BAR|bar|kPa|psi|MPaG|MPaA)",
    "cross_section":   r"(?i)(?:mm\u00b2|mm2|mm\^2|\u33a1)",
    "ring_stiffness":  r"(?i)SN\d+",
    "current":         r"(?i)(?:A|mA|kA|\u5b89\u5ea6)",
    "temperature":     r"(?i)(?:\u00b0C|\u2103|℃|K\b|\u6e29\u5ea6)",
    "length":          r"(?i)(?:m\b|mm|cm|km|\u7c73|\u516c\u91cc)",
    "width":           r"(?i)(?:mm|cm|m\b)",
    "height":          r"(?i)(?:mm|cm|m\b)",
}
# 自由文本字段：值是中文/代号也合理，不受清洗影响
_KNOWN_FREE_TEXT_FIELDS = frozenset({
    "material", "color", "surface", "grade", "form",
    "fire_rating", "ip_rating", "series", "model",
    "drain_type", "inlet_type", "installation_type",
    "usage", "feature", "asphalt_type",
    "breed", "spec", "type", "natural",
    "sn_grade", "strength", "plant_spec",
    "media", "range", "cable_length",
})
# 纯中文描述正则
_PURE_CN_DESC = _re.compile(r"^[\u4e00-\u9fff]+$")
# 归一化替换
_NORMALIZE_SUB = [
    # 数字后 KV → 数字后 kV（regex 不用 \b 因为数字也是 \w）
    (_re.compile(r"(\d)KV(?=[/A-Za-z0-9\s\u4e00-\u9fff]|$)"), r"\1kV"),
    # 词首 KV → kV
    (_re.compile(r"(^|\s)KV(?=[/A-Za-z0-9\s\u4e00-\u9fff]|$)"), r"\1kV"),
]


def _normalize_value(v: str) -> str:
    """归一化字符串（不抛错，所有规则失败返回原文）。"""
    s = str(v).strip()
    for pat, repl in _NORMALIZE_SUB:
        s = pat.sub(repl, s)
    return s


def _is_valid_value(k: str, v: str) -> bool:
    """单一 (k, v) 是否合规，返回 bool。"""
    s = _normalize_value(v)
    if not s:
        return False

    # 数值字段：必须含数字 + 单位；同时拒绝纯中文描述污染
    if k in _NUMERIC_REQUIRED_DIGIT:
        if not _re.search(r"\d", s):
            return False
        if _PURE_CN_DESC.match(s):
            return False
        # 同时配置了单位正则的字段，必须命中
        if k in _NUMERIC_REQUIRED_UNIT and not _re.search(_NUMERIC_REQUIRED_UNIT[k], s):
            return False
        return True

    # 自由文本字段：非空即合法
    if k in _KNOWN_FREE_TEXT_FIELDS:
        return True

    # 其他数值相关字段（仅配置了单位正则，但不在 DIGIT 集合）：仅校验单位
    if k in _NUMERIC_REQUIRED_UNIT:
        return bool(_re.search(_NUMERIC_REQUIRED_UNIT[k], s))

    # 未知 key + 含数字 → 放行（避免破坏真实业务属性）
    # 未知 key + 纯中文 → 拒（高概率是描述文本误投）
    if _PURE_CN_DESC.match(s):
        return False
    return True


def sanitize_attr(flat: dict) -> dict:
    """过滤不合规的 (k, v) 条目，返回清洗后的 dict。供复用 + 单测。"""
    return {k: v for k, v in flat.items() if _is_valid_value(k, v)}


def flat_attr_to_nested(flat: dict) -> list:
    """扁平 attr dict → nested [{k, v}] 列表，写入 DWS。

    v0.9 自动调用 sanitize_attr()，丢弃不合规 v：
      - 数值字段必须含数字
      - 数值字段必须含语义单位
      - 数值字段不能是纯中文描述
    写入时也对 v 做归一化（如 KV → kV）。
    """
    cleaned = sanitize_attr(flat)
    return [{"k": k, "v": _normalize_value(v)} for k, v in cleaned.items() if v]



# ── v0.7+ L3 类目白名单 ──────────────────────────────────────────
_WHITELIST_CACHE: dict = {}
_WHITELIST_PATH_CACHE: dict = {}


def load_l3_whitelist() -> dict:
    """加载 L3 类目 attr 白名单(从 data/category_l3_whitelist.json)。

    v0.7+: 数据驱动生成(由 scripts/gen_l3_whitelist.py 产出)。
    加载后内存缓存,避免每次 parse 都读盘。

    Returns:
        {l3_code: [allowed_attr_key, ...], ...}
        无白名单的 L3 返回 {} → 视为"放行"(保守策略)
    """
    import json
    from pathlib import Path
    # 关键:DATA_DIR 是 monorepo 的 data/(cjt/skills/data/),不是 ETL 私有 data/
    # 白名单由 scripts/gen_l3_whitelist.py 输出到 monorepo 根的 data/,
    # 多个项目(etl / dashboard)共享同一份。
    from gov_price_etl.paths import DATA_DIR

    path = DATA_DIR / "category_l3_whitelist.json"
    if not path.exists():
        return {}
    # 用 mtime 作 cache key,文件更新自动失效
    mtime = path.stat().st_mtime
    if _WHITELIST_PATH_CACHE.get("path") == path and _WHITELIST_PATH_CACHE.get("mtime") == mtime:
        return _WHITELIST_CACHE
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        _WHITELIST_CACHE.clear()
        _WHITELIST_CACHE.update(data)
        _WHITELIST_PATH_CACHE["path"] = path
        _WHITELIST_PATH_CACHE["mtime"] = mtime
        return data
    except Exception:
        return {}


def filter_by_l3_whitelist(parsed: dict, l3: str) -> dict:
    """白名单过滤:L3 不在白名单的 key 丢弃;L3 无白名单 = 放行(保守)。"""
    whitelist = load_l3_whitelist()
    allowed = whitelist.get(l3)
    if not allowed:
        return parsed  # 无白名单 = 放行
    allowed_set = set(allowed)
    return {k: v for k, v in parsed.items() if k in allowed_set}

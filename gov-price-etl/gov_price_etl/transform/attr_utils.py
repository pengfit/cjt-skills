"""transform/attr_utils.py - attr 字段提取与转换工具

被 DWD→DWS 同步流程复用，处理三种历史遗留格式：
  1. nested attr 字段（新格式，list of {k, v}）
  2. attr_* 前缀字段（旧 ETL 写入）
  3. 顶层扁平字段（手动修复或历史遗留）
"""
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

    优先提取 nested attr 字段（新格式），同时兼容 attr_* 前缀字段和顶层扁平字段（历史遗留）。
    """
    attr = {}

    # 标准路径 1：nested attr 字段
    nested = doc.get("attr")
    if nested and isinstance(nested, list):
        for item in nested:
            if isinstance(item, dict):
                k = item.get("k", "")
                v = item.get("v", "")
                if k and v and str(v).lower() not in ("", "null", "none"):
                    attr[k] = str(v)

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


def flat_attr_to_nested(flat: dict) -> list:
    """扁平 attr dict → nested [{k, v}] 列表，写入 DWS。"""
    return [{"k": k, "v": v} for k, v in flat.items() if v]


# ── backward compat shims（老代码用 _build_attr / _flat_attr_to_nested）──
def _build_attr(doc: dict) -> dict:
    return build_attr(doc)


def _flat_attr_to_nested(flat: dict) -> list:
    return flat_attr_to_nested(flat)

"""parse_spec - 按城市分发的规格解析器

目录结构:
  __init__.py      # get_parser() 入口
  base.py          # BaseParseSpec 通用规则
  xian.py          # 西安（暂无需额外规则）
  sichuan.py       # 四川（预留）
  henan.py         # 河南（预留）
  ...
  rules/
    _attrs.py          # ATTR_SLOTS 定义
    vector_store.py    # SQLite 向量规则库（DB_PATH 由 paths.SPEC_RULES_DB 解析）

用法:
  from gov_price_etl.parse_spec import get_parser
  parser = get_parser("xian")
  result = parser.parse("H100~H250")

  # 或通用入口
  from gov_price_etl.parse_spec import parse_spec
  result = parse_spec("δ=4.5", city="base")
"""
from .base import BaseParseSpec

CITY_PARSERS = {
    "xian":      ("xian",      "XianParseSpec"),
    "sichuan":   ("sichuan",   "SichuanParseSpec"),
    "chongqing": ("base",      None),   # 暂用通用规则
    "jinan":     ("base",      None),   # 暂用通用规则
    "rizhao":    ("base",      None),   # 暂用通用规则
    "henan":     ("henan",     "HenanParseSpec"),
}

def get_parser(city: str = "base") -> BaseParseSpec:
    """按城市获取对应解析器。未知城市或 'base' 走通用 BaseParseSpec。"""
    if city not in CITY_PARSERS:
        return BaseParseSpec()
    mod_name, cls_name = CITY_PARSERS[city]
    if cls_name is None or mod_name == "base":
        return BaseParseSpec()
    import importlib
    mod = importlib.import_module(f"gov_price_etl.parse_spec.{mod_name}")
    return getattr(mod, cls_name)()


def parse_spec(s: str, city: str = "base", breed: str = "", category: str = "") -> dict:
    """通用入口：parse_spec("δ=4.5", city="xian") → {"thickness": "4.5"}"""
    return get_parser(city).parse(s, breed, category)

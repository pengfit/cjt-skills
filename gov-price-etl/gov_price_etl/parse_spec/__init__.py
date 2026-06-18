"""parse_spec - 规格解析器（按城市分发，当前统一走通用规则）

目录结构:
  __init__.py      # get_parser() 入口
  base.py          # BaseParseSpec 通用规则
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

扩展：未来若某城市出现特化规格模式，在 parse_spec/<city>.py 里定义
   class <City>ParseSpec(BaseParseSpec):
       def _city_rules(self, s, result): ...
   然后在 CITY_PARSERS 加一行 ("<city>", "<module>", "<ClassName>") 即可。
"""
from .base import BaseParseSpec

# 当前所有城市都走通用 BaseParseSpec（无城市特化规则）。
# 预留扩展点：未来加城市特化时，把 "base" 改成 "xian" / "<module>"，
# 在 __class__ 字段填 "XianParseSpec" / "<ClassName>"。
CITY_PARSERS = {
    "xian":      ("base", None),
    "sichuan":   ("base", None),
    "chongqing": ("base", None),
    "jinan":     ("base", None),
    "rizhao":    ("base", None),
    "henan":     ("base", None),
}


def get_parser(city: str = "base") -> BaseParseSpec:
    """按城市获取对应解析器。未知城市或 'base' 走通用 BaseParseSpec。"""
    entry = CITY_PARSERS.get(city)
    if entry is None:
        return BaseParseSpec()
    mod_name, cls_name = entry
    if cls_name is None or mod_name == "base":
        return BaseParseSpec()
    import importlib
    mod = importlib.import_module(f"gov_price_etl.parse_spec.{mod_name}")
    return getattr(mod, cls_name)()


def parse_spec(s: str, city: str = "base", breed: str = "", category: str = "") -> dict:
    """通用入口：parse_spec("δ=4.5", city="xian") → {"thickness": "4.5"}"""
    return get_parser(city).parse(s, breed, category)

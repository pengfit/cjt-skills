"""parse_spec - 按城市分发的规格解析器

目录结构:
  __init__.py      # get_parser() 入口
  base.py          # BaseParseSpec 通用规则
  xian.py          # 西安（暂无需额外规则）
  sichuan.py       # 四川（预留）
  chongqing.py     # 重庆（预留）
  jinan.py         # 济南（预留）
  rizhao.py        # 日照（预留）

用法:
  from parse_spec import get_parser
  parser = get_parser("xian")   # 西安解析器
  result = parser.parse("H100~H250")

  # 或通用入口（默认 xian）
  from parse_spec import parse_spec
  result = parse_spec("δ=4.5", city="base")
"""
from .base import BaseParseSpec, clean_spec

CITY_PARSERS = {
    "xian":     ("xian",     "XianParseSpec"),
    "sichuan":  ("sichuan",  "SichuanParseSpec"),
    "chongqing":("base",     None),   # 暂用通用规则
    "jinan":    ("base",     None),   # 暂用通用规则
    "rizhao":   ("base",     None),   # 暂用通用规则
}


def get_parser(city: str = "xian"):
    """根据城市获取对应的 parse_spec 解析器实例"""
    module_name, class_name = CITY_PARSERS.get(city, ("base", None))
    if module_name == "base" or class_name is None:
        return BaseParseSpec()
    try:
        mod = __import__(f".{module_name}", fromlist=[class_name])
        return getattr(mod, class_name)()
    except (ImportError, AttributeError):
        return BaseParseSpec()


def parse_spec(spec: str, city: str = "xian") -> dict:
    """通用入口，按城市分发到对应解析器"""
    return get_parser(city).parse(spec)


__all__ = ["BaseParseSpec", "get_parser", "parse_spec", "clean_spec"]
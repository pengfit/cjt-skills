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
from .cable import parse_cable_spec, is_cable_breed, _canon_voltage  # v0.10 cable GB/T 12706


class _CableAwareParseSpec:
    """Wrapper: cable breed 先走 GB/T 12706 专用解析, 其余走基类 city parser。

    集成方式: get_parser() 返回本类, 调用方完全无感知。
    行为: breed 含电缆关键词 →  cable_attrs + city_attrs 但排除 cable 相关字段
         否则                   →  city_attrs (原逻辑)

    为防止 base parser 对电缆 spec 的错误抽取 (如把'0.6'当 diameter='6mm'),
    cable 路径上从 city_attrs 中排除 cable 专管字段, 避免冲突。
    """

    # cable parser 专管的字段, base parser 不许写
    _CABLE_OWNED_KEYS = frozenset({
        "type", "voltage", "core_count", "cross_section", "fire_rating", "armor_type",
    })

    def __init__(self, city_parser: BaseParseSpec):
        self._city_parser = city_parser

    def parse(self, spec: str, breed: str = "", category: str = "", l3: str = "") -> dict:
        if not spec or spec == "/":
            return {}
        # 电缆专用解析（仅当 breed 命中电缆关键词）
        if is_cable_breed(breed or ""):
            cable_attrs = parse_cable_spec(spec, breed)
            if cable_attrs:
                # cable parser 足够完整, 跳过 base parser (避免数字误填噪声)
                # 过滤 None / 空值
                return {k: v for k, v in cable_attrs.items() if v is not None and v != ""}
        # 非 cable 路径 或 cable 不匹配 → 走 base parser 原逻辑
        return self._city_parser.parse(spec, breed, category, l3)

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
    "heze":      ("base", None),
    "qingdao":   ("base", None),
    "weihai":    ("base", None),
    "hainan":    ("base", None),
    "guizhou":   ("base", None),
}


def get_parser(city: str = "base") -> BaseParseSpec:
    """按城市获取对应解析器。未知城市或 'base' 走通用 BaseParseSpec。

    v0.10 起返回 _CableAwareParseSpec wrapper, 透明支持电缆 GB/T 12706 命名。
    """
    entry = CITY_PARSERS.get(city)
    if entry is None:
        city_parser = BaseParseSpec()
    else:
        mod_name, cls_name = entry
        if cls_name is None or mod_name == "base":
            city_parser = BaseParseSpec()
        else:
            import importlib
            mod = importlib.import_module(f"gov_price_etl.parse_spec.{mod_name}")
            city_parser = getattr(mod, cls_name)()
    return _CableAwareParseSpec(city_parser)


def parse_spec(s: str, city: str = "base", breed: str = "",
               category: str = "",  # v0.8+ 已弃用,保留兼容旧调用
               l3: str = "") -> dict:
    """通用入口：parse_spec("δ=4.5", city="xian", l3="01.05.15") → {"thickness": "4.5"}

    v0.8+: category 参数已弃用（L3 蕴含 category）,新代码用 l3 代替。
    """
    return get_parser(city).parse(s, breed, category, l3)

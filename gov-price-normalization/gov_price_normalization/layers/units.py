"""L2 单位换算层

职责：
- 把单位字符串解析为 {dim, to_base, base}
- 同量纲内做数值换算
- 按 v3 L3 default_unit 做价格归一化

依赖：
- utils/data_loader.py（数据）
- utils/errors.py（异常）

不依赖：其它层、ETL、ES
"""
from __future__ import annotations
import re
import unicodedata
from typing import Optional
from ..utils.data_loader import load_json
from ..utils.errors import UnknownUnitError, DimensionMismatchError

_DATA_FILE = "unit_conversion.json"


def _units_table() -> dict:
    return load_json(_DATA_FILE)["units"]


def l3_default_unit(l3_code: str) -> Optional[str]:
    """取 v3 L3 分类的默认单位（如 01.05.07 → m³）。L3 未登记返回 None。"""
    table = load_json(_DATA_FILE).get("l3_default_unit", {})
    if l3_code in table and not l3_code.startswith("_"):
        return table[l3_code]
    return None


def parse_unit(unit_str: Optional[str]) -> dict:
    """解析单位字符串。

    Args:
        unit_str: 原始单位字符串（含变体、OCR 错误、数字连写等）

    Returns:
        dict: {raw, dim, to_base, base, normalized}；未知单位抛 UnknownUnitError
              空字符串 → {raw:'', dim:None, to_base:1.0, base:'', normalized:''}

    兼容增量 (2026-08-01):
      - PDF OCR 全角 → 半角 (NFKC normalize): ｔ→t, １→1, １０个→10个
      - 数字+单位连写 → 拆数字: 10个→个, 100套→套, 1.5米→米
      - 中文变体 alias: 立方米→m³, 公斤→kg 等
    """
    if unit_str is None or unit_str == "":
        return {"raw": "", "dim": None, "to_base": 1.0, "base": "", "normalized": ""}
    raw = unit_str.strip()
    if not raw:
        return {"raw": "", "dim": None, "to_base": 1.0, "base": "", "normalized": ""}
    # 常见中文变体归一
    alias = {
        "立方米": "m³", "立方": "m³", "方": "m³",
        "平米": "m²", "平方": "m²", "㎡": "m²",
        "公斤": "kg", "千克": "kg",
        "公吨": "t",
        "千米": "km", "公里": "km",
        "公分": "cm",
        "公厘": "mm",
        # 2026-08-01: ASCII 上下标变体 (PDF OCR 误识别)
        "m2": "m²", "m3": "m³",
        # 2026-08-01: 大小写变体 (柴油类常用 lowercase 'l',但表里是 'L')
        "l": "L", "L": "L",
        # 2026-08-01: 复合单位归一
        "m2/m": "m", "m²/m": "m",  # 面积/长度 = 长度
    }
    table = _units_table()
    # 多级 normalize 候选序列（按优先级）:
    #   1. raw 本身
    #   2. NFKC (全角 → 半角): ｔ→t, １→1, １０个→10个
    #   3. 去内部空格: 千 块 → 千块
    #   4. 去括号内容: 箱（305米） → 箱
    #   5. 去元/前缀 (价格漏到 unit): 元/m2 → m2
    #   6. 数字前缀剥离 (含小数 + 连字符): 10个→个, 100套→套, 10-15杆→杆
    #   7. 组合: NFKC+空格/NFKC+括号/NFKC+元/NFKC+数字
    candidates = [raw]
    seen = {raw}
    queue = [raw]
    while queue:
        s = queue.pop(0)
        # 1. NFKC
        nfkc = unicodedata.normalize('NFKC', s)
        if nfkc not in seen:
            seen.add(nfkc); candidates.append(nfkc); queue.append(nfkc)
        # 2. 去内部空格
        no_space = re.sub(r'\s+', '', s)
        if no_space != s and no_space not in seen:
            seen.add(no_space); candidates.append(no_space); queue.append(no_space)
        # 3. 去括号内容
        no_paren = re.sub(r'[（(].*?[)）]', '', s).strip()
        if no_paren and no_paren != s and no_paren not in seen:
            seen.add(no_paren); candidates.append(no_paren); queue.append(no_paren)
        # 4. 去元/前缀
        no_yuan = re.sub(r'^元[/／]?', '', s)
        if no_yuan != s and no_yuan not in seen:
            seen.add(no_yuan); candidates.append(no_yuan); queue.append(no_yuan)
        # 5. 数字前缀剥离 (含小数 + 连字符)
        no_digits = re.sub(r'^[\d\.\-]+\s*', '', s)
        if no_digits and no_digits != s and no_digits not in seen:
            seen.add(no_digits); candidates.append(no_digits); queue.append(no_digits)
    for c in candidates:
        normalized = alias.get(c, c)
        if normalized in table:
            info = table[normalized]
            return {
                "raw": raw,
                "dim": info["dim"],
                "to_base": info["to_base"],
                "base": info["base"],
                "normalized": normalized,
            }
    raise UnknownUnitError(f"未知单位: {raw!r}", raw=raw, field="unit")


def convert_value(value: float, from_unit: str, to_unit: str) -> float:
    """同量纲数值换算（数量场景）。

    Examples:
        >>> convert_value(1, "t", "kg")
        1000.0
        >>> convert_value(100, "mm", "m")
        0.1
    """
    f = parse_unit(from_unit)
    t = parse_unit(to_unit)
    if f["dim"] != t["dim"]:
        raise DimensionMismatchError(
            f"量纲不匹配: {from_unit!r}({f['dim']}) → {to_unit!r}({t['dim']})",
            field="unit",
        )
    # value × from_to_base → 转到基本单位 → ÷ to_to_base → 转到目标单位
    if t["to_base"] == 0:
        raise DimensionMismatchError(f"目标单位换算系数为 0: {to_unit!r}", field="unit")
    return value * f["to_base"] / t["to_base"]


def convert_price(price: float, from_unit: str, to_unit: str) -> float:
    """价格换算（price per unit 场景，量纲与数值方向相反）。

    含义：price 表示「每 1 个 from_unit 的元数」。
    目标：「每 1 个 to_unit 的元数」。

    Examples:
        >>> convert_price(4, "kg", "t")        # 4 元/kg = 4000 元/t
        4000.0
        >>> convert_price(5000, "t", "kg")     # 5000 元/t = 5 元/kg
        5.0
        >>> convert_price(100, "mm", "m")      # 100 元/mm = 0.1 元/m
        0.1
    """
    # 价格 = 元/单位，单位变大 1 倍则价格变大 N 倍（因为 N 个 from = 1 个 to）
    f = parse_unit(from_unit)
    t = parse_unit(to_unit)
    if f["dim"] != t["dim"]:
        raise DimensionMismatchError(
            f"量纲不匹配: {from_unit!r}({f['dim']}) → {to_unit!r}({t['dim']})",
            field="unit",
        )
    if t["to_base"] == 0:
        raise DimensionMismatchError(f"目标单位换算系数为 0: {to_unit!r}", field="unit")
    # 1 个 to_unit = (t.to_base / f.to_base) 个 from_unit
    # price_per_to = price_per_from × (1 to_unit 的 from_unit 数)
    return price * t["to_base"] / f["to_base"]


def normalize_price_to_l3(price: float, from_unit: str, l3_code: str) -> dict:
    """按 v3 L3 的 default_unit 把价格归一化。

    Returns:
        dict: {
          'price_canonical': float,    # 归一后的价格
          'unit_canonical': str,        # 归一后的单位（"m³" 等）
          'converted': bool,            # 是否真的换算了（False = 单位一致或 L3 无 default）
          'factor': float,              # 换算因子
        }
    """
    target = l3_default_unit(l3_code)
    if target is None:
        # L3 没登记 default_unit → 不换算，原样返回
        return {
            "price_canonical": price,
            "unit_canonical": from_unit,
            "converted": False,
            "factor": 1.0,
        }
    src = parse_unit(from_unit)
    if src["dim"] is None:
        # 原单位无法解析 → 不换算
        return {
            "price_canonical": price,
            "unit_canonical": from_unit,
            "converted": False,
            "factor": 1.0,
        }
    if src["normalized"] == target:
        return {
            "price_canonical": price,
            "unit_canonical": target,
            "converted": False,
            "factor": 1.0,
        }
    try:
        new_price = convert_price(price, from_unit, target)
    except DimensionMismatchError:
        # 量纲不匹配（如 piece vs mass）→ 不换算
        return {
            "price_canonical": price,
            "unit_canonical": from_unit,
            "converted": False,
            "factor": 1.0,
        }
    return {
        "price_canonical": round(new_price, 4),
        "unit_canonical": target,
        "converted": True,
        "factor": new_price / price if price else 1.0,
    }
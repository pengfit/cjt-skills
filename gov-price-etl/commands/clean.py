"""clean.py - gov-price 数据清洗逻辑

处理品种、规格、单位的标准化。
"""

import re
from typing import Optional


# ─── 单位映射 (统一为标准单位) ─────────────────────────────────────────────────
UNIT_STD_MAP = {
    "t": "t", "吨": "t", "吨/吨": "t",
    "kg": "kg", "千克": "kg", "公斤": "kg",
    "m³": "m³", "立方": "m³", "m3": "m³", "立方米": "m³",
    "m²": "m²", "平米": "m²", "平方米": "m²", "m2": "m²",
    "m": "m", "米": "m", "延米": "m",
    "个": "个", "只": "个", "支": "个", "套": "个",
    "根": "根", "节": "根", "段": "根",
    "卷": "卷", "桶": "桶", "袋": "袋", "包": "袋",
    "块": "块", "块/块": "块", "张": "张",
}

# ─── 品种名清洗 ─────────────────────────────────────────────────────────────────
def clean_breed(breed: str) -> str:
    """去除品种名中的噪声字符，保留核心名称"""
    if not breed:
        return ""
    b = breed.strip()
    # 统一全角/标点符号（问号/顿号等干扰分词）
    b = b.replace('\uff1f', '').replace('\u3001', '').replace('\uff0c', ',').replace('?', '').replace('x', '')
    # 去除前后空格和常见噪声词
    noise = ["（含税）", "(含税)", "（报价）", "(报价)", "【报价】", "【含税】"]
    for n in noise:
        b = b.replace(n, "")
    b = re.sub(r'[,，\s]+', '', b)
    return b.strip()


# ─── 规格清洗 ───────────────────────────────────────────────────────────────────
def clean_spec(spec: str) -> str:
    """标准化规格字符串"""
    if not spec:
        return ""
    s = spec.strip()
    # 统一乘号
    s = s.replace("×", "*").replace("X", "*").replace("x", "*")
    # 去除多余空格
    s = re.sub(r'\s+', '', s)
    # 统一单位符号大小写
    s = s.replace("m³", "m³").replace("M³", "m³")
    return s


# ─── 单位清洗 ───────────────────────────────────────────────────────────────────
def clean_unit(unit: str) -> str:
    """标准化单位字符串"""
    if not unit:
        return ""
    u = unit.strip().lower()
    return UNIT_STD_MAP.get(u, u)


# ─── 价格字段清洗 ───────────────────────────────────────────────────────────────
def clean_price(price) -> Optional[float]:
    """将价格转为浮点数，无效返回 None"""
    if price is None:
        return None
    try:
        return float(price)
    except (ValueError, TypeError):
        return None





if __name__ == "__main__":
    import sys
    print(f"UNIT_STD_MAP: {len(UNIT_STD_MAP)} entries")
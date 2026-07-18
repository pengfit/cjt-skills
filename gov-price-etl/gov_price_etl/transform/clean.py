"""clean.py - gov-price 数据入仓逻辑

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

# 尾部后缀剥离规则（从尾到头循环尝试，最多 4 层）
# 目的：把 ODS "PE100给水管 1.6MPa" → "PE100给水管"，与 DB 规则对齐
# 2026-07-02 重庆 ETL 复盘：19 个失败品种全是「品种+规格后缀」粘在一起，DB 没存核心名
_SUFFIX_PATTERNS = [
    # 末尾括号注释（中文/英文括号，含数字/角度等）
    (r'（[^）]*\d[^）]*）$', ''),
    (r'\([^)]*\d[^)]*\)$', ''),
    (r'（[^）]*°[^）]*）$', ''),
    (r'\([^)]*°[^)]*\)$', ''),
    # 末尾温度（℃ / °C）
    (r'\d+[℃°C]$', ''),
    # 末尾 SDRxx/x.xMPa
    (r'SDR\d+/\d+(\.\d+)?MPa$', ''),
    # 末尾压力（MPa / kPa / bar）
    (r'\d+(\.\d+)?(MPa|kPa|mPa|bar|Bar)$', ''),
    # 末尾电压（kV / V）
    (r'\d+(\.\d+)?(kV|KV|V)$', ''),
    # 末尾管道/管件型号：B 型 / A 型（可能后跟"管/材/片"等量词）
    (r'[A-Z]型[管材片块]$', ''),
    (r'[A-Z]型$', ''),
    # 末尾任意括号注释（含说明文字，无数字也可）—— 例：低辐射、品牌注释
    # 注意：只剥末尾括号，**不**剥内联括号——内联括号常是关键信息（如 HDPE、PE-RT、PP-R 等材质标识）
    (r'（[^）]*）$', ''),
    (r'\([^)]*\)$', ''),
    # 末尾电缆/电线型号段：以 2+ 大写字母开头、含连字符/数字/斜杠、可能含电压
    # 例: NW-RTTYZ-B1-0.6/1kV、BV-450/750V、WDZAN-YJY23-B1-0.6/1kV、YJV-10KV
    (r'[A-Z]{2,}[-A-Z0-9./]*\d+[-A-Z0-9./]*$', ''),
]


def _strip_suffix(s: str) -> str:
    """循环剥离尾部后缀（最多 4 层），返回核心名"""
    if not s:
        return s
    for _ in range(4):
        prev = s
        for pat, repl in _SUFFIX_PATTERNS:
            new = re.sub(pat, repl, s)
            if new != s:
                s = new
        if s == prev:
            break
    return s.strip()


def clean_breed(breed: str) -> str:
    """去除品种名中的噪声字符，剥离尾部规格/型号后缀，保留核心名称

    2026-06-30 增强：
    - 全角括号统一为半角（让 ODS "（PP-R）" 和 DB "(PP-R)" 可匹配）
    - 压力单位大小写规范化（Mpa → MPa、mpa → MPa）

    2026-07-02 增强（重庆 ETL 复盘）：
    - 剥离尾部规格/型号后缀（MPa / kV / ℃ / B 型 / SDRxx / 电缆型号段等）
    - 目的：让 "PE100给水管 1.6MPa" → "PE100给水管"，与 DB 规则对齐
    """
    if not breed:
        return ""
    b = breed.strip()
    # 统一全角/标点符号（问号/顿号等干扰分词）
    b = b.replace('\uff1f', '').replace('\u3001', '').replace('\uff0c', ',').replace('?', '').replace('x', '')
    # 2026-06-30: 全角括号 → 半角（PP-R 系列 ODS/DB 括号风格不统一）
    b = b.replace('（', '(').replace('）', ')')
    b = b.replace('【', '[').replace('】', ']')
    # 2026-06-30: 压力单位大小写规范化（ODS 用 Mpa，DB 用 MPa）
    b = re.sub(r'(?<=[A-Za-z])pa', 'Pa', b)  # mpa → mPa, Mpa → MPa
    # 去除前后空格和常见噪声词
    noise = ["（含税）", "(含税)", "（报价）", "(报价)", "【报价】", "【含税】"]
    for n in noise:
        b = b.replace(n, "")
    b = re.sub(r'[,，\s]+', '', b)
    b = b.strip()
    # 2026-07-02: 剥离尾部规格/型号后缀，让核心名回归 DB
    b = _strip_suffix(b)
    return b.strip()


# ─── 规格清洗 ───────────────────────────────────────────────────────────────────
def clean_spec(spec: str) -> str:
    """标准化规格字符串

    2026-07-18 改造（威海 ETL 复盘）：
    - **保留内部空格** —— 空格在某些规格中是有效分隔符（如 "H 形钢"、"DN 65"、"C 30"），
      删掉会导致后续 parse_spec / breed_spec_rules.db 召回率下降
    - 只做头尾 strip（去爬虫无关空白），不删内部空格
    """
    if not spec:
        return ""
    s = spec.strip()
    # 统一乘号
    s = s.replace("×", "*").replace("X", "*").replace("x", "*")
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
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""parse_price.py - 价格区间解析（通用）

从 chongqing v3 (2026-07-02) 抽出，升级为通用工具：
- 支持单值、区间（多种分隔符）、大于/小于、特殊描述词
- 所有边界值（price_min/price_max）与中位数（price）同时返回
- 区间字符串原样保留（用于 price_range 字段）
- 特殊描述词（如'全冠'）走 notes 路径，不进数值字段

迁移史：
- 2026-07-02：chongqing v3 write_es._parse_interval_price 抽出，落地
- 后续：jiangxi/sichuan/jinan 等场景复用同一套解析

公开 API：
    from gov_price_etl.parse_price import parse_interval_price
    mid, mn, mx, is_range, raw, notes = parse_interval_price('115-173')
"""
import re
from typing import Tuple

# ── 区间分隔符（多种风格支持，省平台各异） ─────────────────────
_RANGE_SEP = r'[-~到至]'

# ── 特殊描述词（不入数值，进 notes） ────────────────────────────
# 园林景观里 '全冠'/'全干' 表示"全部到顶/到干"，是合法价格描述。
# 各城市陆续会加新词，按需扩充；前缀匹配即可。
_KNOWN_SPECIAL = {"全冠", "全干"}

# ── 预编译正则（性能优化，每条记录都要调一次） ───────────────
_RE_SINGLE = re.compile(r'^-?\d+(?:\.\d+)?$')
_RE_RANGE = re.compile(rf'^(-?\d+(?:\.\d+)?)\s*{_RANGE_SEP}\s*(-?\d+(?:\.\d+)?)$')
_RE_GT = re.compile(r'^[大小]于\s*(-?\d+(?:\.\d+)?)$|>\s*(-?\d+(?:\.\d+)?)')
_RE_LT = re.compile(r'^[小]于\s*(-?\d+(?:\.\d+)?)$|<\s*(-?\d+(?:\.\d+)?)')


def _nz(x):
    """非零判断（None/0/0.0 都视为空）。"""
    return (x is not None) and (x != 0) and (x != 0.0)


def parse_interval_price(s: str) -> Tuple[float, float, float, bool, str, str]:
    """解析价格字符串，返回 (mid, min, max, is_range, raw, notes)。

    参数：
        s: 原始字符串（如 '3353.98' / '115-173' / '大于200' / '全冠' / ''）

    返回：6 元组
        mid      - 中位数（用于 price 字段，排序筛选统计）
        mn       - 区间下界（用于 price_min；DWS 价格有效性判断用）
        mx       - 区间上界（用于 price_max；趋势分析上界用）
        is_range - 是否为区间价（用于 is_range）
        raw      - 原始字符串规范化（用于 price_range）
        notes    - 特殊描述（如 '全冠'），存进 range_notes

    支持格式：
        '3353.98'              → (3353.98, 3353.98, 3353.98, False, '3353.98', '')
        '115-173'              → (144.0,   115.0,   173.0,   True,  '115-173', '')
        '115~173'              → (144.0,   115.0,   173.0,   True,  '115~173', '')
        '115到173'             → (144.0,   115.0,   173.0,   True,  '115到173', '')
        '大于200' / '>200'     → (200.0,   200.0,   200.0,   True,  '>200',    '')
        '小于100' / '<100'     → (100.0,   100.0,   100.0,   True,  '<100',    '')
        '全冠' / '全干'        → (0.0,     0.0,     0.0,     True,  '全冠',    '全冠')
        '' / None              → (0.0,     0.0,     0.0,     False, '',        '')

    边界处理：
        - 输入非字符串（int/float）→ 转字符串后重试
        - 输入包含全角符号（￥、,、元、空格）→ 自动清洗
        - 区间倒序（'173-115'）→ 自动排序成 (115, 173)
        - 区间解析失败 → 兜底走特殊词检查；都不是 → 走 notes 路径
    """
    if s is None:
        return (0.0, 0.0, 0.0, False, '', '')
    if not isinstance(s, str):
        s = str(s)
    raw = s.strip()
    if not raw:
        return (0.0, 0.0, 0.0, False, '', '')

    # 全角符号清洗（￥/元/中文逗号/空格，不影响数字）
    s_clean = re.sub(r'[￥,，元\s]', '', raw)

    # 1) 单值
    m = _RE_SINGLE.fullmatch(s_clean)
    if m:
        val = float(m.group(0))
        return (val, val, val, False, raw, '')

    # 2) 区间（支持 - / ~ / 到 / 至）
    m = _RE_RANGE.match(s_clean)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        lo, hi = (a, b) if a <= b else (b, a)
        return ((lo + hi) / 2, lo, hi, True, raw, '')

    # 3) 大于 / '>200'
    m = _RE_GT.match(raw) or _RE_GT.match(s_clean)
    if m:
        val = float(m.group(1) or m.group(2))
        return (val, val, val, True, raw, '')

    # 4) 小于 / '<100'
    m = _RE_LT.match(raw) or _RE_LT.match(s_clean)
    if m:
        val = float(m.group(1) or m.group(2))
        return (val, val, val, True, raw, '')

    # 5) 已知特殊词
    if raw in _KNOWN_SPECIAL:
        return (0.0, 0.0, 0.0, True, raw, raw)

    # 6) 兜底：未知字符串，进 notes 路径（不入数值，避免污染价格统计）
    return (0.0, 0.0, 0.0, True, raw, raw)


# ── 便捷函数（更直观语义）──────────────────────────────────

def is_price_valid(price_min: float, price_max: float = None, price: float = None,
                   tax_price: float = None, tax_min: float = None) -> bool:
    """价格有效性统一判断（DWS 过滤用）。

    优先级（与原 dws_sync._is_price_valid 一致）：
        1) price_min（区间下界）
        2) tax_min
        3) price（单值）
        4) tax_price

    任意一个非零即视为有效（说明该品种在源站有发布价格）。

    背景：偏远区县、未发布品种、绿化苗木"全冠"等场景，源站价格为空/0，
    写进 DWS 会污染价格走势/排序/统计。
    """
    if _nz(price_min):
        return True
    if _nz(tax_min):
        return True
    if _nz(price):
        return True
    if _nz(tax_price):
        return True
    return False


__all__ = [
    "parse_interval_price",
    "is_price_valid",
    "KNOWN_SPECIAL",
]


if __name__ == "__main__":
    # 自测
    samples = [
        "3353.98", "115-173", "115~173", "115到173", "115至173",
        "大于200", ">200", "小于100", "<100",
        "全冠", "全干", "", None, 0, 0.0,
        "￥3,353.98 元", "173-115",  # 全角清洗 + 区间倒序
        "面议",  # 兜底
    ]
    print(f"{'input':25s} | {'mid':>10s} {'min':>10s} {'max':>10s} | is_range | raw")
    print("-" * 90)
    for s in samples:
        mid, mn, mx, is_r, raw, notes = parse_interval_price(s)
        print(f"{str(s)!r:25s} | {mid:>10.2f} {mn:>10.2f} {mx:>10.2f} | {str(is_r):8s} | {raw!r:12s} notes={notes!r}")
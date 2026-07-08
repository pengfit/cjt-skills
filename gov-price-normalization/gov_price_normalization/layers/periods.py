"""L3 业务期对齐层

职责：
- 把各城市的 period_start 字符串归一到 canonical（YYYY-MM / YYYY-Qn）
- 季刊 / 双月刊按 anchor_month 桶化
- 不定期（irregular）保留原始月份

依赖：
- utils/data_loader.py
- utils/errors.py

不依赖：其它层、ETL、ES
"""
from __future__ import annotations
import re
from datetime import datetime
from typing import Optional
from ..utils.data_loader import load_json
from ..utils.errors import UnknownCityError, UnparseablePeriodError

_DATA_FILE = "period_rules.json"


def city_granularity(city: str) -> str:
    """取城市粒度（monthly / quarterly / bimonthly / irregular）。

    Raises:
        UnknownCityError: 城市未登记
    """
    rules = load_json(_DATA_FILE)
    if city not in rules:
        raise UnknownCityError(f"未知城市: {city!r}", city=city, field="city")
    return rules[city]["granularity"]


def city_anchor_months(city: str) -> Optional[list]:
    """季刊/双月刊的发布月份；monthly/irregular 返回 None。"""
    rules = load_json(_DATA_FILE)
    if city not in rules:
        return None
    return rules[city].get("anchor_month")


def _parse_any(s: str) -> Optional[datetime]:
    """尝试多种常见格式解析 period_start。"""
    s = s.strip()
    if not s:
        return None
    fmts = [
        "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S", "%Y/%m/%d",
        "%Y.%m", "%Y.%m.%d",
        "%Y%m%d", "%Y%m",
    ]
    # 先尝试完整日期
    for fmt in fmts[:6]:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    # 再尝试 YYYYMM / YYYY.MM
    for fmt in fmts[6:]:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    # 尝试 "2026年02月" / "2026年2月"
    m = re.match(r"^(\d{4})年(\d{1,2})月(?:\d{1,2}日)?$", s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), 1)
        except ValueError:
            return None
    # 尝试 "2026-Q1" / "2026Q1" / "2026 Q1"
    m = re.match(r"^(\d{4})\s*[-]?\s*[Qq]\s*[-]?\s*(\d)$", s)
    if m:
        # 季度 → 用该季度的第一个月
        year, q = int(m.group(1)), int(m.group(2))
        month = (q - 1) * 3 + 1
        try:
            return datetime(year, month, 1)
        except ValueError:
            return None
    return None


def _bucket_granularity(dt: datetime, granularity: str, anchor_months: Optional[list]) -> str:
    """把日期按城市粒度归桶，返回 canonical key。"""
    y, m = dt.year, dt.month
    if granularity == "monthly":
        return f"{y}-{m:02d}"
    if granularity == "quarterly":
        # 找最近的 anchor_month（向前向下取）
        if anchor_months:
            # 季度对应月份：1,4,7,10
            q_month = max([am for am in anchor_months if am <= m], default=anchor_months[0] - 3)
            if q_month < 1:
                q_month = anchor_months[0] - 3
            return f"{y}-Q{(q_month - 1) // 3 + 1}"
        # 没 anchor_month，按 (m-1)//3 算
        return f"{y}-Q{(m - 1) // 3 + 1}"
    if granularity == "bimonthly":
        # 默认按相邻 anchor_month 桶（如 anchor=[2,4,6,8,10,12]，5月→4月）
        if anchor_months:
            bucket = max([am for am in anchor_months if am <= m], default=anchor_months[0])
            if bucket > m:
                # 跨年回退
                bucket = anchor_months[-1]  # 上一年的最后一期
                return f"{y - 1}-{bucket:02d}"
            return f"{y}-{bucket:02d}"
        return f"{y}-{m:02d}"
    # irregular → 原样
    return f"{y}-{m:02d}"


def normalize_period(period_start: Optional[str], city: str) -> dict:
    """把 period_start 归一到 canonical。

    Args:
        period_start: 原始字符串，如 '2026-02-15' / '2026.1' / '2026-Q1' / '2026年02月'
        city: 城市 key

    Returns:
        dict: {
          'raw': str,
          'parsed': str,         # 解析后的 YYYY-MM-DD
          'canonical': str,      # canonical key: 'YYYY-MM' or 'YYYY-Qn'
          'year': int,
          'month': Optional[int],
          'quarter': Optional[int],
          'granularity': str,    # monthly/quarterly/bimonthly/irregular
        }

    Raises:
        UnknownCityError: 城市未登记
        UnparseablePeriodError: 字符串无法解析
    """
    rules = load_json(_DATA_FILE)
    if city not in rules:
        raise UnknownCityError(f"未知城市: {city!r}", city=city, field="city")
    granularity = rules[city]["granularity"]
    anchor = rules[city].get("anchor_month")
    raw = period_start or ""
    dt = _parse_any(raw)
    if dt is None:
        raise UnparseablePeriodError(
            f"period_start 无法解析: {raw!r}", raw=raw, city=city, field="period_start",
        )
    canonical = _bucket_granularity(dt, granularity, anchor)
    # 推 quarter
    quarter = None
    if granularity == "quarterly":
        m = re.match(r"^(\d{4})-Q(\d)$", canonical)
        if m:
            quarter = int(m.group(2))
    elif granularity == "monthly" or granularity == "bimonthly":
        m = re.match(r"^(\d{4})-(\d{2})$", canonical)
        if m:
            quarter = (int(m.group(2)) - 1) // 3 + 1
    return {
        "raw": raw,
        "parsed": dt.strftime("%Y-%m-%d"),
        "canonical": canonical,
        "year": dt.year,
        "month": dt.month,
        "quarter": quarter,
        "granularity": granularity,
    }


def align_periods(periods: list[str], city: str) -> list[dict]:
    """批量对齐——返回 list of normalize_period 结果（顺序与入参一致）。"""
    return [normalize_period(p, city) for p in periods]
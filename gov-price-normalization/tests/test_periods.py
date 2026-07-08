"""tests/test_periods.py — L3 periods 层单元测试"""
import unittest
import sys
from pathlib import Path

_PKG = Path(__file__).resolve().parent.parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from gov_price_normalization.layers import periods
from gov_price_normalization.utils.errors import UnknownCityError, UnparseablePeriodError


class TestNormalizePeriod(unittest.TestCase):

    def test_monthly_basic(self):
        # 西安月刊
        out = periods.normalize_period("2026-02-15", "xian")
        self.assertEqual(out["canonical"], "2026-02")
        self.assertEqual(out["year"], 2026)
        self.assertEqual(out["month"], 2)
        self.assertEqual(out["quarter"], 1)
        self.assertEqual(out["granularity"], "monthly")

    def test_monthly_chinese_format(self):
        out = periods.normalize_period("2026年02月", "xian")
        self.assertEqual(out["canonical"], "2026-02")
        self.assertEqual(out["year"], 2026)
        self.assertEqual(out["month"], 2)

    def test_monthly_short_format(self):
        out = periods.normalize_period("2026.2", "xian")
        self.assertEqual(out["canonical"], "2026-02")
        self.assertEqual(out["month"], 2)

    def test_quarterly_weihai(self):
        # 威海季刊，anchor_month=[1,4,7,10]
        out = periods.normalize_period("2026-02-15", "weihai")
        # 2月最近 anchor 是 1月 → canonical="2026-Q1"
        self.assertEqual(out["canonical"], "2026-Q1")
        self.assertEqual(out["quarter"], 1)
        self.assertEqual(out["granularity"], "quarterly")

        out = periods.normalize_period("2026-04-01", "weihai")
        self.assertEqual(out["canonical"], "2026-Q2")

        out = periods.normalize_period("2026-05-20", "weihai")
        # 5月最近 anchor 是 4月 → Q2
        self.assertEqual(out["canonical"], "2026-Q2")

        out = periods.normalize_period("2026-12-31", "weihai")
        self.assertEqual(out["canonical"], "2026-Q4")

    def test_quarterly_explicit_q(self):
        # 直接传季度字符串
        out = periods.normalize_period("2026-Q3", "weihai")
        self.assertEqual(out["canonical"], "2026-Q3")
        self.assertEqual(out["quarter"], 3)

    def test_bimonthly_ningxia(self):
        # 宁夏双月刊，anchor_month=[2,4,6,8,10,12]
        out = periods.normalize_period("2026-03-15", "ningxia")
        # 3月最近 anchor 是 2月 → 2026-02
        self.assertEqual(out["canonical"], "2026-02")

        out = periods.normalize_period("2026-06-01", "ningxia")
        self.assertEqual(out["canonical"], "2026-06")

        out = periods.normalize_period("2026-07-15", "ningxia")
        # 7月最近 anchor 是 6月
        self.assertEqual(out["canonical"], "2026-06")

    def test_bimonthly_jan(self):
        # 1月找不到向前 anchor → 用 12 月（跨年）
        out = periods.normalize_period("2026-01-15", "ningxia")
        self.assertEqual(out["canonical"], "2025-12")

    def test_irregular_jinan(self):
        # 济南 irregular → 保留原月份
        out = periods.normalize_period("2026-03-15", "jinan")
        self.assertEqual(out["canonical"], "2026-03")
        self.assertEqual(out["granularity"], "irregular")

    def test_unknown_city(self):
        with self.assertRaises(UnknownCityError):
            periods.normalize_period("2026-02-15", "atlantis")

    def test_unparseable(self):
        with self.assertRaises(UnparseablePeriodError):
            periods.normalize_period("not-a-date", "xian")
        with self.assertRaises(UnparseablePeriodError):
            periods.normalize_period("", "xian")

    def test_year_quarter_calc_monthly(self):
        # monthly 的 quarter 字段（按月推季度）
        out = periods.normalize_period("2026-08-15", "xian")
        self.assertEqual(out["quarter"], 3)  # 8月→Q3
        out = periods.normalize_period("2026-11-15", "xian")
        self.assertEqual(out["quarter"], 4)  # 11月→Q4


class TestCityGranularity(unittest.TestCase):

    def test_known(self):
        self.assertEqual(periods.city_granularity("xian"), "monthly")
        self.assertEqual(periods.city_granularity("weihai"), "quarterly")
        self.assertEqual(periods.city_granularity("ningxia"), "bimonthly")
        self.assertEqual(periods.city_granularity("jinan"), "irregular")

    def test_unknown(self):
        with self.assertRaises(UnknownCityError):
            periods.city_granularity("atlantis")


class TestAlignPeriods(unittest.TestCase):

    def test_batch(self):
        ps = ["2026-01-15", "2026-02-15", "2026-03-15", "2026-04-15"]
        out = periods.align_periods(ps, "xian")
        self.assertEqual([o["canonical"] for o in out],
                         ["2026-01", "2026-02", "2026-03", "2026-04"])


if __name__ == "__main__":
    unittest.main()
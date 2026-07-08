"""tests/test_units.py — L2 units 层单元测试"""
import unittest
import sys
from pathlib import Path

_PKG = Path(__file__).resolve().parent.parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from gov_price_normalization.layers import units
from gov_price_normalization.utils.errors import UnknownUnitError, DimensionMismatchError


class TestParseUnit(unittest.TestCase):

    def test_basic_mass(self):
        self.assertEqual(units.parse_unit("kg")["dim"], "mass")
        self.assertEqual(units.parse_unit("t")["to_base"], 1000000.0)
        self.assertEqual(units.parse_unit("kg")["to_base"], 1000.0)  # 1 kg = 1000 g
        self.assertEqual(units.parse_unit("g")["to_base"], 1.0)
        self.assertEqual(units.parse_unit("mg")["to_base"], 0.001)
        self.assertEqual(units.parse_unit("吨")["dim"], "mass")

    def test_basic_length(self):
        self.assertEqual(units.parse_unit("mm")["to_base"], 1.0)
        self.assertEqual(units.parse_unit("cm")["to_base"], 10.0)
        self.assertEqual(units.parse_unit("m")["to_base"], 1000.0)

    def test_area_volume(self):
        self.assertEqual(units.parse_unit("m²")["dim"], "area")
        self.assertEqual(units.parse_unit("m³")["dim"], "volume")
        self.assertEqual(units.parse_unit("L")["dim"], "volume")

    def test_piece(self):
        for u in ["个", "只", "根", "块", "套", "件", "台"]:
            info = units.parse_unit(u)
            self.assertEqual(info["dim"], "piece", f"{u} 应是 piece")

    def test_chinese_alias(self):
        self.assertEqual(units.parse_unit("立方米")["normalized"], "m³")
        self.assertEqual(units.parse_unit("公斤")["normalized"], "kg")
        self.assertEqual(units.parse_unit("公吨")["normalized"], "t")
        self.assertEqual(units.parse_unit("平方")["normalized"], "m²")

    def test_empty_and_none(self):
        empty = units.parse_unit("")
        self.assertIsNone(empty["dim"])
        none = units.parse_unit(None)
        self.assertIsNone(none["dim"])

    def test_unknown_unit(self):
        with self.assertRaises(UnknownUnitError):
            units.parse_unit("光年")


class TestConvertValue(unittest.TestCase):

    def test_mass(self):
        self.assertEqual(units.convert_value(1, "t", "kg"), 1000.0)
        self.assertEqual(units.convert_value(1000, "kg", "t"), 1.0)
        self.assertEqual(units.convert_value(1, "吨", "kg"), 1000.0)

    def test_length(self):
        self.assertEqual(units.convert_value(1, "m", "mm"), 1000.0)
        self.assertEqual(units.convert_value(100, "mm", "m"), 0.1)
        self.assertEqual(units.convert_value(1, "km", "m"), 1000.0)

    def test_area(self):
        self.assertEqual(units.convert_value(1, "m²", "mm²"), 1000000.0)
        self.assertEqual(units.convert_value(1, "m²", "cm²"), 10000.0)

    def test_volume(self):
        self.assertEqual(units.convert_value(1, "m³", "L"), 1000.0)
        self.assertEqual(units.convert_value(1, "L", "m³"), 0.001)

    def test_piece_no_convert(self):
        # piece 类内部不互转（根 vs 个 业务语义不同）
        self.assertEqual(units.convert_value(5, "根", "个"), 5.0)

    def test_dimension_mismatch(self):
        with self.assertRaises(DimensionMismatchError):
            units.convert_value(1, "kg", "m")
        with self.assertRaises(DimensionMismatchError):
            units.convert_value(1, "m²", "m³")


class TestNormalizePriceToL3(unittest.TestCase):

    def test_steel_kg_to_t(self):
        # 钢材 L3 (01.01.01) default = "t"
        # 100 元/kg = 100000 元/t
        out = units.normalize_price_to_l3(100, "kg", "01.01.01")
        self.assertEqual(out["unit_canonical"], "t")
        self.assertEqual(out["price_canonical"], 100000.0)
        self.assertTrue(out["converted"])

    def test_same_unit_no_convert(self):
        out = units.normalize_price_to_l3(500, "m³", "01.05.07")
        self.assertEqual(out["unit_canonical"], "m³")
        self.assertEqual(out["price_canonical"], 500)
        self.assertFalse(out["converted"])

    def test_dimension_mismatch_no_convert(self):
        # kg vs m³ → 量纲不匹配，不换算（保留原值）
        out = units.normalize_price_to_l3(500, "kg", "01.05.07")
        self.assertFalse(out["converted"])
        self.assertEqual(out["price_canonical"], 500)
        self.assertEqual(out["unit_canonical"], "kg")

    def test_piece_l3(self):
        # 个位数 L3 01.06.01 default="个"，根→个 1:1
        out = units.normalize_price_to_l3(50, "根", "01.06.01")
        self.assertEqual(out["unit_canonical"], "个")
        self.assertEqual(out["price_canonical"], 50)

    def test_unknown_l3(self):
        out = units.normalize_price_to_l3(100, "kg", "99.99.99")
        # L3 没登记 → 不换算
        self.assertFalse(out["converted"])
        self.assertEqual(out["price_canonical"], 100)
        self.assertEqual(out["unit_canonical"], "kg")


class TestL3DefaultUnit(unittest.TestCase):

    def test_known_l3(self):
        self.assertEqual(units.l3_default_unit("01.01.01"), "t")
        self.assertEqual(units.l3_default_unit("01.05.07"), "m³")

    def test_unknown_l3(self):
        self.assertIsNone(units.l3_default_unit("99.99.99"))


if __name__ == "__main__":
    unittest.main()
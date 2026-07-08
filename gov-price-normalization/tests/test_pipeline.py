"""tests/test_pipeline.py — pipeline 串联层单元测试"""
import unittest
import sys
from pathlib import Path

_PKG = Path(__file__).resolve().parent.parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from gov_price_normalization import normalize_doc, normalize_batch


class TestNormalizeDoc(unittest.TestCase):

    def test_basic_hainan_cement(self):
        """散装水泥 + 海南月刊 + 01.05.07 L3"""
        doc = {
            "breed": "散装水泥",
            "unit": "t",
            "price": 350,
            "period_start": "2026-02-15",
        }
        out = normalize_doc(doc, "hainan", l3_code="01.05.07")
        # L3 periods
        self.assertEqual(out["canonical_period"], "2026-02")
        self.assertEqual(out["period_norm"]["month"], 2)
        # L2 units parse
        self.assertEqual(out["unit_norm"]["dim"], "mass")
        # L2 price normalize: t → m³ for 01.05.07（量纲不匹配，应降级）
        self.assertFalse(out["price_norm"]["converted"])
        self.assertEqual(out["price_norm"]["price_canonical"], 350)
        # status
        self.assertEqual(out["_norm"]["status"]["L3_periods"], "ok")
        self.assertEqual(out["_norm"]["status"]["L2_units_parse"], "ok")
        self.assertEqual(out["_norm"]["status"]["L2_price_normalize"], "skipped")

    def test_steel_xian_kg_to_t(self):
        """钢筋 + 西安月刊 + 01.01.01 L3 → kg→t 归一"""
        doc = {
            "breed": "热轧带肋钢筋",
            "unit": "kg",
            "price": 4.5,
            "period_start": "2026-02-15",
        }
        out = normalize_doc(doc, "xian", l3_code="01.01.01")
        self.assertEqual(out["canonical_period"], "2026-02")
        self.assertTrue(out["price_norm"]["converted"])
        self.assertEqual(out["price_norm"]["unit_canonical"], "t")
        self.assertEqual(out["price_norm"]["price_canonical"], 4500.0)

    def test_weihai_quarterly(self):
        """威海季刊 → Q1 桶化"""
        doc = {
            "breed": "混凝土",
            "unit": "m³",
            "price": 480,
            "period_start": "2026-02-15",
        }
        out = normalize_doc(doc, "weihai", l3_code="01.05.07")
        self.assertEqual(out["canonical_period"], "2026-Q1")
        self.assertEqual(out["period_norm"]["quarter"], 1)
        # m³ → m³ 同单位不换算
        self.assertFalse(out["price_norm"]["converted"])
        self.assertEqual(out["price_norm"]["price_canonical"], 480)

    def test_no_l3_no_price_norm(self):
        """不传 l3 → 不做价格归一，但其他层照常"""
        doc = {"breed": "x", "unit": "kg", "price": 100, "period_start": "2026-02"}
        out = normalize_doc(doc, "xian")
        self.assertNotIn("price_norm", out)
        self.assertEqual(out["canonical_period"], "2026-02")

    def test_unknown_city_degrades(self):
        doc = {"breed": "x", "unit": "kg", "price": 100, "period_start": "2026-02"}
        # 降级模式（strict=False）：L3 抛错但不抛整体异常
        out = normalize_doc(doc, "atlantis")
        self.assertIn("error:", out["_norm"]["status"]["L3_periods"])
        # canonical_period 降级为原值
        self.assertEqual(out["canonical_period"], "2026-02")
        # 其他层照常
        self.assertEqual(out["unit_norm"]["dim"], "mass")

    def test_unknown_unit_degrades(self):
        doc = {"breed": "x", "unit": "光年", "price": 100, "period_start": "2026-02"}
        out = normalize_doc(doc, "xian")
        self.assertIn("error:", out["_norm"]["status"]["L2_units_parse"])
        # unit_norm 保留 raw
        self.assertEqual(out["unit_norm"]["raw"], "光年")
        self.assertIsNone(out["unit_norm"]["dim"])

    def test_strict_raises(self):
        from gov_price_normalization.utils.errors import UnknownCityError
        doc = {"breed": "x", "unit": "kg", "price": 100, "period_start": "2026-02"}
        with self.assertRaises(UnknownCityError):
            normalize_doc(doc, "atlantis", strict=True)

    def test_input_not_modified(self):
        """normalize_doc 不修改入参"""
        doc = {"breed": "x", "unit": "kg", "price": 100, "period_start": "2026-02"}
        snapshot = dict(doc)
        normalize_doc(doc, "xian", l3_code="01.01.01")
        self.assertEqual(doc, snapshot)


class TestNormalizeBatch(unittest.TestCase):

    def test_batch(self):
        docs = [
            {"breed": "钢", "unit": "kg", "price": 4, "period_start": "2026-02-15"},
            {"breed": "钢", "unit": "kg", "price": 5, "period_start": "2026-03-15"},
        ]
        out = normalize_batch(docs, "xian", l3_code="01.01.01")
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["price_norm"]["price_canonical"], 4000.0)
        self.assertEqual(out[1]["price_norm"]["price_canonical"], 5000.0)
        self.assertEqual(out[0]["canonical_period"], "2026-02")
        self.assertEqual(out[1]["canonical_period"], "2026-03")


if __name__ == "__main__":
    unittest.main()
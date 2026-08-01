"""tests/test_cross_city.py — L4 跨城映射层单元测试（v0.3，2026-08-01）

覆盖：
  - canonicalize: 命中 / 未命中 / 空 / DB 异常降级
  - expand_to_cities: 反向索引 / 空 canonical / cities 透传
  - align_spec_across_cities: v0.3 占位透传
  - pipeline 串联：L4 写入 normalized_breed / _canonical_source / _l3_code
"""
import unittest
import sys
from pathlib import Path

_PKG = Path(__file__).resolve().parent.parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from gov_price_normalization.layers import cross_city as L_cross
from gov_price_normalization import normalize_doc


class TestCanonicalize(unittest.TestCase):
    """L4.canonicalize — breed_clean 单条查表"""

    def test_hit_with_l3(self):
        # 已知品种：'热轧带肋钢筋(盘螺)' 应命中 (l3_code=01.05.15, source=ai_dify)
        hit = L_cross.canonicalize("热轧带肋钢筋(盘螺)", city="xian")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["breed_clean"], "热轧带肋钢筋(盘螺)")
        self.assertEqual(hit["normalized_breed"], "热轧带肋钢筋")
        self.assertEqual(hit["l3_code"], "01.05.15")
        self.assertEqual(hit["source"], "ai_dify")
        self.assertGreater(hit["confidence"], 0.0)

    def test_miss_returns_none(self):
        # 野生品种：未入 canonical.db
        hit = L_cross.canonicalize("某稀有野生物种XYZ", city="xian")
        self.assertIsNone(hit)

    def test_empty_breed_returns_none(self):
        hit = L_cross.canonicalize("", city="xian")
        self.assertIsNone(hit)
        hit2 = L_cross.canonicalize("   ", city="xian")
        self.assertIsNone(hit2)

    def test_city_only_context(self):
        # city 不影响查表行为（v0.3 范围）
        hit1 = L_cross.canonicalize("热轧带肋钢筋(盘螺)", city="xian")
        hit2 = L_cross.canonicalize("热轧带肋钢筋(盘螺)", city="sichuan")
        self.assertEqual(hit1["normalized_breed"], hit2["normalized_breed"])


class TestExpandToCities(unittest.TestCase):
    """L4.expand_to_cities — canonical 反向索引"""

    def test_expand_known(self):
        out = L_cross.expand_to_cities("热轧带肋钢筋")
        self.assertEqual(out["canonical_breed"], "热轧带肋钢筋")
        self.assertGreater(len(out["breed_cleans"]), 0)
        # 至少包含「热轧带肋钢筋(盘螺)」
        self.assertIn("热轧带肋钢筋(盘螺)", out["breed_cleans"])
        # by_breed 字段含 l3_code
        self.assertEqual(out["by_breed"]["热轧带肋钢筋(盘螺)"]["l3_code"], "01.05.15")

    def test_expand_unknown_returns_empty(self):
        out = L_cross.expand_to_cities("完全未知归一化名")
        self.assertEqual(out["breed_cleans"], [])
        self.assertEqual(out["by_breed"], {})

    def test_expand_empty_canonical(self):
        out = L_cross.expand_to_cities("")
        self.assertEqual(out["breed_cleans"], [])

    def test_cities_param_passthrough(self):
        # cities 在 v0.3 仅透传，DB 层不参与过滤
        out = L_cross.expand_to_cities("热轧带肋钢筋", cities=["xian", "sichuan"])
        self.assertEqual(out["cities_filter"], ["xian", "sichuan"])
        self.assertGreater(len(out["breed_cleans"]), 0)


class TestAlignSpecV03(unittest.TestCase):
    """L4.align_spec_across_cities — v0.3 占位透传"""

    def test_passthrough(self):
        spec = {"grade": "HPB300", "diameter": "Φ10"}
        out = L_cross.align_spec_across_cities(spec, cities=["xian"])
        self.assertEqual(out, spec)


class TestPipelineL4Integration(unittest.TestCase):
    """normalize_doc 串联：L4 必须写 normalized_breed / _canonical_source / _l3_code"""

    def _base_doc(self, breed_clean: str) -> dict:
        return {
            "breed": breed_clean,
            "breed_clean": breed_clean,
            "unit": "t",
            "price": 3500,
            "period_start": "2026-02-15",
            "attr": [],
        }

    def test_l4_hit_writes_canonical(self):
        out = normalize_doc(self._base_doc("热轧带肋钢筋(盘螺)"), city="xian")
        self.assertEqual(out["normalized_breed"], "热轧带肋钢筋")
        self.assertEqual(out["_canonical_source"], "ai_dify")
        self.assertEqual(out["_l3_code"], "01.05.15")
        self.assertGreater(out["_canonical_confidence"], 0.0)
        self.assertEqual(out["_norm"]["status"]["L4_cross_city"], "ok")

    def test_l4_miss_writes_raw_fallback(self):
        out = normalize_doc(self._base_doc("某稀有野生物种XYZ"), city="xian")
        self.assertEqual(out["normalized_breed"], "某稀有野生物种XYZ")
        self.assertEqual(out["_canonical_source"], "raw_fallback")
        self.assertIsNone(out["_l3_code"])
        self.assertEqual(out["_canonical_confidence"], 0.0)
        self.assertEqual(out["_norm"]["status"]["L4_cross_city"], "skipped_raw_fallback")

    def test_l4_empty_breed(self):
        d = self._base_doc("")
        d["breed"] = ""
        d["breed_clean"] = ""
        out = normalize_doc(d, city="xian")
        self.assertIsNone(out["normalized_breed"])
        self.assertIsNone(out["_canonical_source"])
        self.assertEqual(out["_norm"]["status"]["L4_cross_city"], "skipped_empty")

    def test_l4_uses_breed_when_breed_clean_missing(self):
        # 仅 breed 字段：退化到 breed
        d = {"breed": "热轧带肋钢筋(盘螺)", "unit": "t", "price": 3500,
             "period_start": "2026-02-15", "attr": []}
        out = normalize_doc(d, city="xian")
        self.assertEqual(out["normalized_breed"], "热轧带肋钢筋")
        self.assertEqual(out["_canonical_source"], "ai_dify")


class TestVersion(unittest.TestCase):
    """_norm.version 必须是 0.3.0（L4 解锁标记）"""

    def test_version_0_3_0(self):
        d = {"breed_clean": "test", "unit": "t", "price": 1,
             "period_start": "2026-02-15", "attr": []}
        out = normalize_doc(d, city="xian")
        self.assertEqual(out["_norm"]["version"], "0.3.0")


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_transform_doc.py - transform_doc 单文档转换测试

覆盖：
  1. 默认行为（v2_override=None → 调 classify_v2）
  2. v2_override 外部传入（跳过查表直接用，ETL pipeline 批量 AI 场景）
  3. v2_override 字段映射（14 个 v2 字段透传到 DWD）
  4. spec 为空时的 breed 填充
  5. 空 breed 跳过
  6. v2_override 的字段类型容错（None / 空字典）

运行：python3 -m pytest tests/test_transform_doc.py -v
或： python3 tests/test_transform_doc.py        （无 pytest 时自测）
"""
import sys
import unittest
from pathlib import Path

TEST_DIR = Path(__file__).parent
PROJECT_ROOT = TEST_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from gov_price_etl.classify.category_v2 import (
    classify_v2,
    close_singleton,
)
from gov_price_etl.transform import transform_doc


# 完整 v2 字典（模拟 service.classify_v2_batch 返回结果）
MOCK_AI_V2 = {
    "l1": "01", "l2": "01.04", "l3": "01.04.01", "l4": "UNCLASSIFIED",
    "gb_50500": "010601", "quota_ref": "5-31",
    "ifc_class": "IfcBeam", "uniclass_ss": "Ss_20_20_20",
    "eng_part": "主体", "eng_stage": "施工", "main_or_aux": "主材",
    "unit": "t", "billing_unit": "t", "cost_method": "清单",
    "name_l1": "建筑工程", "name_l2": "钢筋工程", "name_l3": "钢构件",
    "category_v2_source": "ai_v2", "category_v2_confidence": 0.92,
    "material_code": "MAT-001",
}


class TestTransformDoc(unittest.TestCase):

    def setUp(self):
        close_singleton()

    def test_default_uses_classify_v2(self):
        """默认行为：v2_override=None → 调 classify_v2 5 段式"""
        raw = {"breed": "圆钢", "spec": "Φ20", "unit": "t"}
        doc = transform_doc(raw, "ods_test", "xian")
        # 默认走 DB 查表，结果应包含完整 v2 字段
        self.assertIn("category_l1", doc)
        self.assertIn("category_l3", doc)
        self.assertIn("category_v2_source", doc)

    def test_v2_override_skip_query(self):
        """v2_override 外部传入 → 跳过查表直接用"""
        raw = {"breed": "测试品种", "spec": "Φ20", "unit": "t"}
        doc = transform_doc(raw, "ods_test", "xian", v2_override=MOCK_AI_V2)

        # 14 个 v2 字段应透传
        self.assertEqual(doc["category_l1"], "01")
        self.assertEqual(doc["category_l2"], "01.04")
        self.assertEqual(doc["category_l3"], "01.04.01")
        self.assertEqual(doc["category_l4"], "UNCLASSIFIED")
        self.assertEqual(doc["category_name_l1"], "建筑工程")
        self.assertEqual(doc["category_name_l2"], "钢筋工程")
        self.assertEqual(doc["category_name_l3"], "钢构件")
        self.assertEqual(doc["category"], "建筑工程")
        self.assertEqual(doc["eng_part"], "主体")
        self.assertEqual(doc["eng_stage"], "施工")
        self.assertEqual(doc["main_or_aux"], "主材")
        self.assertEqual(doc["gb_50500"], "010601")
        self.assertEqual(doc["quota_ref"], "5-31")
        self.assertEqual(doc["ifc_class"], "IfcBeam")
        self.assertEqual(doc["uniclass_ss"], "Ss_20_20_20")
        self.assertEqual(doc["material_code"], "MAT-001")
        self.assertEqual(doc["category_v2_source"], "ai_v2")
        self.assertEqual(doc["category_v2_confidence"], 0.92)

    def test_v2_override_doesnt_call_db(self):
        """v2_override 传入时，即使 DB 没数据也能正常转换（不依赖 DB）"""
        # breed_clean 一个 DB 里绝对没有的字符串
        raw = {"breed": "完全不存在的虚构品种XYZ_9999", "spec": "", "unit": "m³"}
        # 默认行为：DB 没命中 → fallback
        doc_default = transform_doc(raw, "ods_test", "xian")
        # v2_override 行为：直接用 override 数据
        doc_override = transform_doc(raw, "ods_test", "xian", v2_override=MOCK_AI_V2)

        # 默认会走 fallback（unit），v2_override 会用 AI 数据
        self.assertNotEqual(
            doc_default["category_v3_confidence"] if "category_v3_confidence" in doc_default else doc_default.get("category_v2_source", ""),
            doc_override["category_v2_source"],
        )
        self.assertEqual(doc_override["category_v2_source"], "ai_v2")

    def test_v2_override_none_fields_handled(self):
        """v2_override 字段为 None 时不应崩溃（用空字符串兜底）"""
        partial_v2 = {
            "l1": "01", "l2": "", "l3": "", "l4": "UNCLASSIFIED",
            "name_l1": "建筑工程", "name_l2": "", "name_l3": "",
            "category_v2_source": "ai_v2", "category_v2_confidence": 0.7,
            # 其他字段缺失 → 用 "" 兜底
        }
        raw = {"breed": "测试", "spec": "", "unit": ""}
        doc = transform_doc(raw, "ods_test", "xian", v2_override=partial_v2)
        # 不应 KeyError
        self.assertEqual(doc["category_l1"], "01")
        self.assertEqual(doc["category_name_l1"], "建筑工程")

    def test_v2_override_empty_dict(self):
        """v2_override={} 空字典不应崩溃（用空字符串兜底）"""
        raw = {"breed": "测试", "spec": "", "unit": ""}
        doc = transform_doc(raw, "ods_test", "xian", v2_override={})
        # 空 dict 时 category_v2_source 为 ""
        self.assertEqual(doc["category_v2_source"], "")

    def test_spec_slash_normalized(self):
        """spec='/' 应先规范为空，后回填为 breed（链式处理）"""
        raw = {"breed": "圆钢", "spec": "/", "unit": "t"}
        doc = transform_doc(raw, "ods_test", "xian", v2_override=MOCK_AI_V2)
        # '/' → '' → 回填为 breed_clean (圆钢)
        self.assertEqual(doc["spec"], "圆钢")

    def test_spec_empty_filled_with_breed_clean(self):
        """spec 为空时，spec 应回填为 breed_clean"""
        raw = {"breed": "圆钢", "spec": "", "unit": "t"}
        doc = transform_doc(raw, "ods_test", "xian", v2_override=MOCK_AI_V2)
        # breed_clean 是 clean_breed 后的结果，可能是原值或归一化版本
        self.assertTrue(doc["spec"])
        # 应该是 breed 回填
        self.assertIn(doc["spec"], ["圆钢", doc["breed_clean"]])

    def test_spec_normal_when_present(self):
        """spec 有值时不应被覆盖"""
        raw = {"breed": "圆钢", "spec": "Φ20 高强", "unit": "t"}
        doc = transform_doc(raw, "ods_test", "xian", v2_override=MOCK_AI_V2)
        self.assertEqual(doc["spec"], "Φ20 高强")

    def test_default_uses_real_db_data(self):
        """真实 DB 数据测试（依赖 breed_l3_map 有数据）"""
        raw = {"breed": "圆钢", "spec": "Φ20", "unit": "t"}
        doc = transform_doc(raw, "ods_test", "xian")
        # 圆钢在 breed_l3_map 里（DB 里有 AI 校验过的数据）
        # 应有 category_l3 = '01.04.01'（钢构件）
        if doc["category_v2_source"] in ("db_exact_v2", "db_fuzzy_v2"):
            self.assertEqual(doc["category_l1"], "01")


# ── etl_city 两轮 ETL 逻辑测试 ───────────────────────────────────────
class TestEtlTwoPassLogic(unittest.TestCase):
    """测试 pipeline.etl 的'先 DB 后 AI'两轮逻辑（不依赖 ES，仅验证逻辑分支）。"""

    def test_local_hit_sources_includes_db_and_pattern(self):
        """DB 命中阈值应包含 db_exact_v2 / db_fuzzy_v2 / pattern_v2"""
        from gov_price_etl.pipeline.etl import _LOCAL_HIT_SOURCES
        self.assertIn("db_exact_v2", _LOCAL_HIT_SOURCES)
        self.assertIn("db_fuzzy_v2", _LOCAL_HIT_SOURCES)
        self.assertIn("pattern_v2", _LOCAL_HIT_SOURCES)
        # 不应包含 fallback（unit 推断）或 no_match
        self.assertNotIn("fallback_v2", _LOCAL_HIT_SOURCES)
        self.assertNotIn("no_match_v2", _LOCAL_HIT_SOURCES)
        self.assertNotIn("ai_v2", _LOCAL_HIT_SOURCES)

    def test_db_hit_decision(self):
        """DB 命中判断逻辑"""
        from gov_price_etl.pipeline.etl import _LOCAL_HIT_SOURCES
        # 命中场景
        self.assertTrue("db_exact_v2" in _LOCAL_HIT_SOURCES)
        self.assertTrue("db_fuzzy_v2" in _LOCAL_HIT_SOURCES)
        self.assertTrue("pattern_v2" in _LOCAL_HIT_SOURCES)
        # 未命中场景
        self.assertFalse("fallback_v2" in _LOCAL_HIT_SOURCES)
        self.assertFalse("ai_v2" in _LOCAL_HIT_SOURCES)
        self.assertFalse("no_match_v2" in _LOCAL_HIT_SOURCES)


if __name__ == "__main__":
    print("=" * 60)
    print("  transform.doc + etl_pipeline 两轮 ETL 测试")
    print("=" * 60)
    unittest.main(verbosity=2)
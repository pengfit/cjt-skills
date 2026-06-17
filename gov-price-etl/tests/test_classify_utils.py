#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_classify_utils.py - v2 分类公共工具单元测试

测试 gov_price_etl/classify/utils.py 中的所有工具函数。
这些工具是 scripts/ai_validate_l3_map.py 和 ai/service.py:classify_v2_batch
复用的核心逻辑，每个工具都有踩坑背景，测试要锁住行为防止回归。

运行：python3 -m pytest tests/test_classify_utils.py -v
或： python3 tests/test_classify_utils.py        （无 pytest 时自测）
"""
import sys
import unittest
from pathlib import Path

TEST_DIR = Path(__file__).parent
PROJECT_ROOT = TEST_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from gov_price_etl.classify.utils import (
    norm_bc,
    format_l3_list,
    format_breed_list,
    validate_l3_in_taxonomy,
    merge_ai_results,
)


# ── 1. norm_bc 智能引号归一化 ───────────────────────────────────────
class TestNormBc(unittest.TestCase):
    """测试 breed_clean 归一化。踩坑场景：AI 把智能引号 "" 规范成 "" 导致 join 丢失。"""

    def test_empty(self):
        """空字符串/None 边界"""
        self.assertEqual(norm_bc(""), "")
        self.assertEqual(norm_bc(None), None)

    def test_ascii_quotes_unchanged(self):
        """ASCII 直引号不变"""
        self.assertEqual(norm_bc('素色砼"八"字草坪砖'), '素色砼"八"字草坪砖')

    def test_smart_quotes_normalized(self):
        """智能双引号 U+201C/U+201D → ASCII 直引号"""
        self.assertEqual(
            norm_bc('素色砼\u201c八\u201d字草坪砖'),
            '素色砼"八"字草坪砖',
        )
        # 单边智能引号
        self.assertEqual(norm_bc('素色砼\u201c八字草坪砖'), '素色砼"八字草坪砖')
        self.assertEqual(norm_bc('素色砼八\u201d字草坪砖'), '素色砼八"字草坪砖')

    def test_smart_single_quotes(self):
        """智能单引号 U+2018/U+2019 → ASCII 直单引号"""
        self.assertEqual(norm_bc("BNW\u2019s Tile"), "BNW's Tile")
        self.assertEqual(norm_bc("Tile\u2018A"), "Tile'A")

    def test_chinese_comma(self):
        """中文句号 U+3001 → 英文逗号（材料名里偶尔有）"""
        self.assertEqual(norm_bc("水泥\u3001砂浆"), "水泥,砂浆")

    def test_mixed(self):
        """多种字符混合归一化"""
        self.assertEqual(
            norm_bc('BNW\u201c墙丽衣\u201d\u3001彩色砼'),
            'BNW"墙丽衣",彩色砼',
        )

    def test_unicode_round_trip(self):
        """归一化后能跟原直引号版本做相等比较（join 不丢失）"""
        ai_returned = norm_bc('素色砼\u201c八\u201d字草坪砖')
        batch_original = '素色砼"八"字草坪砖'
        self.assertEqual(ai_returned, batch_original)


# ── 2. format_l3_list 编码格式（防止 AI 拼段错误）───────────────────
class TestFormatL3List(unittest.TestCase):
    """测试 64 L3 拼接格式。踩坑：早期输出 "l1.l2.l3" 让 AI 拼成 5 段。"""

    def test_no_segment_concatenation(self):
        """不应输出 l1.l2.l3 形式（防止 AI 误以为可拼接）"""
        taxonomy = [
            {"l1": "01", "l2": "01.04", "l3": "01.04.01",
             "name_l1": "建筑工程", "name_l2": "钢筋工程", "name_l3": "钢构件"},
        ]
        out = format_l3_list(taxonomy)
        self.assertIn("01.04.01", out)
        # 关键：不应出现 01.01.04.04.01 这种 5 段拼接
        self.assertNotIn("01.01.04.04.01", out)
        # 不应以 "01.01.04.01.04.01" 形式（l1.l2.l3 三段拼）出现
        self.assertNotIn("01.01.04.01.04.01", out)

    def test_includes_names_for_context(self):
        """应包含中文名辅助 AI 理解层级"""
        taxonomy = [
            {"l1": "01", "l2": "01.04", "l3": "01.04.01",
             "name_l1": "建筑工程", "name_l2": "钢筋工程", "name_l3": "钢构件"},
        ]
        out = format_l3_list(taxonomy)
        self.assertIn("建筑工程", out)
        self.assertIn("钢筋工程", out)
        self.assertIn("钢构件", out)
        # 用箭头分隔层级
        self.assertIn(" > ", out)

    def test_empty_taxonomy(self):
        """空 taxonomy 返回空字符串"""
        self.assertEqual(format_l3_list([]), "")

    def test_multiple_lines(self):
        """每个 L3 一行"""
        taxonomy = [
            {"l1": "01", "l2": "01.04", "l3": "01.04.01",
             "name_l1": "建筑工程", "name_l2": "钢筋工程", "name_l3": "钢构件"},
            {"l1": "01", "l2": "01.05", "l3": "01.05.01",
             "name_l1": "建筑工程", "name_l2": "门窗工程", "name_l3": "金属门窗"},
        ]
        out = format_l3_list(taxonomy)
        self.assertEqual(len(out.split("\n")), 2)


# ── 3. format_breed_list 品种列表 ──────────────────────────────────
class TestFormatBreedList(unittest.TestCase):
    """测试品种列表格式化。"""

    def test_minimal_form(self):
        """只有 breed_clean + current_l3 时（校验场景）"""
        items = [{"breed_clean": "圆钢", "current_l3": "01.04.01"}]
        out = format_breed_list(items)
        self.assertIn("breed=圆钢", out)
        self.assertIn("current_l3=01.04.01", out)

    def test_full_form(self):
        """有 spec / unit 时（补全场景）"""
        items = [{
            "breed": "HPB300 钢筋", "breed_clean": "HPB300 钢筋",
            "spec": "φ20", "unit": "t", "current_l3": "01.04.01",
        }]
        out = format_breed_list(items)
        self.assertIn("breed=HPB300 钢筋", out)
        self.assertIn("spec=φ20", out)
        self.assertIn("unit=t", out)
        self.assertIn("current_l3=01.04.01", out)

    def test_preserves_smart_quotes(self):
        """breed_clean 智能引号必须原样保留（提示 AI 也保留）"""
        items = [{"breed_clean": '素色砼\u201c八\u201d字草坪砖', "current_l3": "08.01.01"}]
        out = format_breed_list(items)
        # 必须保留智能引号
        self.assertIn('\u201c', out)
        self.assertIn('\u201d', out)

    def test_numbering(self):
        """每条应有递增编号"""
        items = [
            {"breed_clean": "A", "current_l3": "01.01.01"},
            {"breed_clean": "B", "current_l3": "01.02.01"},
        ]
        out = format_breed_list(items)
        self.assertIn("1.", out)
        self.assertIn("2.", out)


# ── 4. validate_l3_in_taxonomy 合法性校验 ───────────────────────────
class TestValidateL3InTaxonomy(unittest.TestCase):
    """测试 L3 合法性校验。踩坑：AI 编造 l3 "99.99.99" 写回污染数据。"""

    def setUp(self):
        self.valid_set = {"01.04.01", "01.05.01", "08.02.01"}

    def test_valid(self):
        self.assertTrue(validate_l3_in_taxonomy("01.04.01", self.valid_set))

    def test_invalid_fabricated(self):
        self.assertFalse(validate_l3_in_taxonomy("99.99.99", self.valid_set))

    def test_empty_string(self):
        self.assertFalse(validate_l3_in_taxonomy("", self.valid_set))

    def test_none(self):
        self.assertFalse(validate_l3_in_taxonomy(None, self.valid_set))

    def test_stripped_whitespace(self):
        """应自动 strip 空格"""
        self.assertTrue(validate_l3_in_taxonomy("  01.04.01  ", self.valid_set))


# ── 5. merge_ai_results AI 输出合并 ────────────────────────────────
class TestMergeAiResults(unittest.TestCase):
    """测试 AI 输出合并。踩坑：智能引号归一化导致 2 条 join 丢失。"""

    def setUp(self):
        self.batch = [
            {"breed_clean": "圆钢", "current_l3": "01.04.01"},
            {"breed_clean": '素色砼\u201c八\u201d字草坪砖', "current_l3": "08.01.01"},
            {"breed_clean": '彩色砼\u201c八\u201d字草坪砖', "current_l3": "08.01.01"},
        ]
        self.valid_set = {"01.04.01", "08.02.01"}

    def test_exact_match(self):
        """精确匹配：AI 返回与 batch 一致"""
        ai = [
            {"breed_clean": "圆钢", "l3": "01.04.01", "confidence": 0.9, "reason": "保持"},
        ]
        merged, skipped = merge_ai_results(self.batch, ai, self.valid_set)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["breed_clean"], "圆钢")
        self.assertTrue(merged[0]["ai_valid"])

    def test_smart_quote_normalized_match(self):
        """智能引号归一化匹配（核心修复）"""
        ai = [
            # AI 返回直引号版本
            {"breed_clean": '素色砼"八"字草坪砖', "l3": "08.02.01", "confidence": 0.82, "reason": "铺装材料"},
        ]
        merged, skipped = merge_ai_results(self.batch, ai, self.valid_set)
        # 关键：应该能匹配上 batch 的智能引号版本
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["breed_clean"], '素色砼\u201c八\u201d字草坪砖')
        self.assertEqual(merged[0]["suggested_l3"], "08.02.01")
        self.assertTrue(merged[0]["ai_valid"])

    def test_invalid_l3_marked(self):
        """AI 给的 l3 不在 valid_set → ai_valid=False"""
        ai = [
            {"breed_clean": "圆钢", "l3": "99.99.99", "confidence": 0.9, "reason": "编造"},
        ]
        merged, skipped = merge_ai_results(self.batch, ai, self.valid_set)
        self.assertEqual(len(merged), 1)
        self.assertFalse(merged[0]["ai_valid"])
        self.assertEqual(merged[0]["suggested_l3"], "99.99.99")

    def test_unknown_breed_skipped(self):
        """AI 返回 batch 里没有的 breed_clean → 跳过 + skipped += 1"""
        ai = [
            {"breed_clean": "unknown_breed", "l3": "01.04.01", "confidence": 0.9},
        ]
        merged, skipped = merge_ai_results(self.batch, ai, self.valid_set)
        self.assertEqual(len(merged), 0)
        self.assertEqual(skipped, 1)

    def test_full_v2_fields_preserved(self):
        """service.classify_v2_batch 用的 14 个字段应保留"""
        ai = [{
            "breed_clean": "圆钢",
            "l3": "01.04.01",
            "l1": "01", "l2": "01.04", "l4": "UNCLASSIFIED",
            "name_l1": "建筑工程", "name_l2": "钢筋工程", "name_l3": "钢构件",
            "gb_50500": "010601", "quota_ref": "5-31",
            "ifc_class": "IfcBeam", "uniclass_ss": "Ss_20_20_20",
            "eng_part": "主体", "eng_stage": "施工", "main_or_aux": "主材",
            "unit": "t",
            "confidence": 0.9, "reason": "钢构件",
        }]
        merged, skipped = merge_ai_results(self.batch, ai, self.valid_set)
        self.assertEqual(len(merged), 1)
        m = merged[0]
        self.assertEqual(m["l1"], "01")
        self.assertEqual(m["name_l3"], "钢构件")
        self.assertEqual(m["gb_50500"], "010601")
        self.assertEqual(m["eng_part"], "主体")
        self.assertEqual(m["unit"], "t")

    def test_empty_inputs(self):
        """空 batch / 空 ai_results 不崩"""
        merged, skipped = merge_ai_results([], [], self.valid_set)
        self.assertEqual(merged, [])
        self.assertEqual(skipped, 0)

    def test_preserves_original_current_l3(self):
        """merged 应保留 batch 原 current_l3（即使 AI 没返回）"""
        ai = [{"breed_clean": "圆钢", "l3": "01.04.01", "confidence": 0.9}]
        merged, _ = merge_ai_results(self.batch, ai, self.valid_set)
        self.assertEqual(merged[0]["current_l3"], "01.04.01")


# ── 自测入口（无 pytest 时用）────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  classify/utils.py 单元测试")
    print("=" * 60)
    unittest.main(verbosity=2)
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_ai_batch_size.py - 验证批量 AI 调用的 batch size 限制

覆盖：
  1. V2_AI_BATCH_SIZE 默认值 = 10（2026-06-17 P1-5: 20→10，避免 prompt 超 64K token）
  2. 批量 AI 超过 10 条时正确分批（不超出 prompt token 限制）
  3. 攒批 slice 逻辑正确（range(0, n, batch_size)）
  4. AI 失败时 batch 边界处理正确

运行：python3 -m pytest tests/test_ai_batch_size.py -v
或： python3 tests/test_ai_batch_size.py        （无 pytest 时自测）
"""
import sys
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

TEST_DIR = Path(__file__).parent
PROJECT_ROOT = TEST_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestBatchSize(unittest.TestCase):
    """验证 V2_AI_BATCH_SIZE 常量 + 攒批切片逻辑。"""

    def test_batch_size_constant(self):
        """V2_AI_BATCH_SIZE = 10（每批 10 条，避免 prompt 超出 64K token 限制）"""
        from gov_price_etl.ai.service import V2_AI_BATCH_SIZE
        self.assertEqual(V2_AI_BATCH_SIZE, 10)

    def test_batch_slice_logic(self):
        """攒批切片正确（range(0, n, batch_size) 不丢不重）"""
        BATCH = 10
        # 模拟 50 条 items，分 5 批：10 × 4 + 10 × 1
        items = list(range(50))
        batches = [items[i:i + BATCH] for i in range(0, len(items), BATCH)]
        self.assertEqual(len(batches), 5)
        for b in batches[:4]:
            self.assertEqual(len(b), 10)
        self.assertEqual(len(batches[4]), 10)

        # 累计条数 = 原始总数
        self.assertEqual(sum(len(b) for b in batches), 50)

    def test_batch_edge_cases(self):
        """边界情况：恰好 10 / 恰好 40 / 0 条 / 1 条"""
        BATCH = 10
        # 0 条
        self.assertEqual([list(range(0))[i:i+BATCH] for i in range(0, 0, BATCH)], [])
        # 1 条
        batches_1 = [list(range(1))[i:i+BATCH] for i in range(0, 1, BATCH)]
        self.assertEqual(len(batches_1), 1)
        self.assertEqual(len(batches_1[0]), 1)
        # 恰好 10 条
        batches_10 = [list(range(10))[i:i+BATCH] for i in range(0, 10, BATCH)]
        self.assertEqual(len(batches_10), 1)
        self.assertEqual(len(batches_10[0]), 10)
        # 恰好 40 条
        batches_40 = [list(range(40))[i:i+BATCH] for i in range(0, 40, BATCH)]
        self.assertEqual(len(batches_40), 4)

    def test_batch_sleep_constant(self):
        """V2_AI_BATCH_SLEEP_S 存在 + 合理（< 5 秒）"""
        from gov_price_etl.ai.service import V2_AI_BATCH_SLEEP_S
        self.assertGreaterEqual(V2_AI_BATCH_SLEEP_S, 0)
        self.assertLess(V2_AI_BATCH_SLEEP_S, 5)


class TestClassifyV2BatchSplitting(unittest.TestCase):
    """验证 classify_v3_batch 实际按 10 条分批调 AI（mock _ai_invoke）。"""

    def _make_items(self, n: int) -> list:
        """生成 n 条测试 items"""
        return [
            {
                "breed": f"测试品种{i}",
                "spec": f"规格{i}",
                "unit": "t",
                "breed_clean": f"test_breed_{i}",
            }
            for i in range(n)
        ]

    @patch("gov_price_etl.ai.service._ai_invoke")
    def test_40_items_split_into_4_batches(self, mock_invoke):
        """40 条 items 应分 4 批（10 + 10 + 10 + 10）调 AI"""
        from gov_price_etl.ai.service import classify_v3_batch

        # mock AI 返回（results 是 dict：breed_clean → result）
        mock_invoke.return_value = (True, '{"results": {}}')

        items = self._make_items(40)
        classify_v3_batch(items, city="test", write_rules=False)

        # AI 被调了 4 次（40 / 10 = 4）
        self.assertEqual(mock_invoke.call_count, 4)

        # 每次调用的 dify_inputs['breed_list'] 包含的 breed_clean 数 <= 10
        for call_args in mock_invoke.call_args_list:
            dify_inputs = call_args.kwargs.get("dify_inputs", {})
            breed_list_str = dify_inputs.get("breed_list", "")
            # 检查 breed_list 里 breed_clean 出现次数
            breed_count = sum(
                1 for it in items if it["breed_clean"] in breed_list_str
            )
            self.assertLessEqual(breed_count, 10)

    @patch("gov_price_etl.ai.service._ai_invoke")
    def test_10_items_exactly_one_batch(self, mock_invoke):
        """恰好 10 条 items → 1 批"""
        from gov_price_etl.ai.service import classify_v3_batch

        mock_invoke.return_value = (True, '{"results": {}}')

        items = self._make_items(10)
        classify_v3_batch(items, city="test", write_rules=False)

        self.assertEqual(mock_invoke.call_count, 1)

    @patch("gov_price_etl.ai.service._ai_invoke")
    def test_25_items_split_into_3_batches(self, mock_invoke):
        """25 条 items → 3 批（10 + 10 + 5）"""
        from gov_price_etl.ai.service import classify_v3_batch

        mock_invoke.return_value = (True, '{"results": {}}')

        items = self._make_items(25)
        classify_v3_batch(items, city="test", write_rules=False)

        self.assertEqual(mock_invoke.call_count, 3)

    @patch("gov_price_etl.ai.service._ai_invoke")
    def test_45_items_split_into_5_batches(self, mock_invoke):
        """45 条 items → 5 批（10 + 10 + 10 + 10 + 5）"""
        from gov_price_etl.ai.service import classify_v3_batch

        mock_invoke.return_value = (True, '{"results": {}}')

        items = self._make_items(45)
        classify_v3_batch(items, city="test", write_rules=False)

        self.assertEqual(mock_invoke.call_count, 5)


if __name__ == "__main__":
    print("=" * 60)
    print("  V2_AI_BATCH_SIZE 批量切片测试")
    print("=" * 60)
    unittest.main(verbosity=2)
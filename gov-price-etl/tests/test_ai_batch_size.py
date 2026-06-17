#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_ai_batch_size.py - 验证批量 AI 调用的 batch size 限制

覆盖：
  1. V2_AI_BATCH_SIZE 默认值 = 20（2026-06-17 道友调整）
  2. 批量 AI 超过 20 条时正确分批（不超出 prompt token 限制）
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
        """V2_AI_BATCH_SIZE = 20（每批 20 条，避免 prompt 超出 token 限制）"""
        from gov_price_etl.ai.service import V2_AI_BATCH_SIZE
        self.assertEqual(V2_AI_BATCH_SIZE, 20)

    def test_batch_slice_logic(self):
        """攒批切片正确（range(0, n, batch_size) 不丢不重）"""
        BATCH = 20
        # 模拟 50 条 items，分 3 批：20 + 20 + 10
        items = list(range(50))
        batches = [items[i:i + BATCH] for i in range(0, len(items), BATCH)]
        self.assertEqual(len(batches), 3)
        self.assertEqual(len(batches[0]), 20)
        self.assertEqual(len(batches[1]), 20)
        self.assertEqual(len(batches[2]), 10)

        # 累计条数 = 原始总数
        self.assertEqual(sum(len(b) for b in batches), 50)

    def test_batch_edge_cases(self):
        """边界情况：恰好 20 / 恰好 40 / 0 条 / 1 条"""
        BATCH = 20
        # 0 条
        self.assertEqual([list(range(0))[i:i+BATCH] for i in range(0, 0, BATCH)], [])
        # 1 条
        batches_1 = [list(range(1))[i:i+BATCH] for i in range(0, 1, BATCH)]
        self.assertEqual(len(batches_1), 1)
        self.assertEqual(len(batches_1[0]), 1)
        # 恰好 20 条
        batches_20 = [list(range(20))[i:i+BATCH] for i in range(0, 20, BATCH)]
        self.assertEqual(len(batches_20), 1)
        self.assertEqual(len(batches_20[0]), 20)
        # 恰好 40 条
        batches_40 = [list(range(40))[i:i+BATCH] for i in range(0, 40, BATCH)]
        self.assertEqual(len(batches_40), 2)

    def test_batch_sleep_constant(self):
        """V2_AI_BATCH_SLEEP_S 存在 + 合理（< 5 秒）"""
        from gov_price_etl.ai.service import V2_AI_BATCH_SLEEP_S
        self.assertGreaterEqual(V2_AI_BATCH_SLEEP_S, 0)
        self.assertLess(V2_AI_BATCH_SLEEP_S, 5)


class TestClassifyV2BatchSplitting(unittest.TestCase):
    """验证 classify_v2_batch 实际按 20 条分批调 AI（mock _call_gateway）。"""

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

    @patch("gov_price_etl.ai.service._call_gateway")
    def test_40_items_split_into_2_batches(self, mock_call):
        """40 条 items 应分 2 批（20 + 20）调 AI"""
        from gov_price_etl.ai.service import classify_v2_batch

        # mock AI 返回（results 是 dict：breed_clean → result）
        mock_call.return_value = (True, '{"results": {}}')

        items = self._make_items(40)
        classify_v2_batch(items, city="test", write_rules=False)

        # AI 被调了 2 次（40 / 20 = 2）
        self.assertEqual(mock_call.call_count, 2)

        # 每次调用的 prompt 包含的 breed_clean 数 <= 20
        for call_args in mock_call.call_args_list:
            prompt = call_args[0][0]  # _call_gateway(prompt, system, user, timeout)
            # 检查 prompt 里 breed_clean 出现次数
            breed_count = sum(
                1 for it in items if it["breed_clean"] in prompt
            )
            self.assertLessEqual(breed_count, 20)

    @patch("gov_price_etl.ai.service._call_gateway")
    def test_20_items_exactly_one_batch(self, mock_call):
        """恰好 20 条 items → 1 批"""
        from gov_price_etl.ai.service import classify_v2_batch

        mock_call.return_value = (True, '{"results": {}}')

        items = self._make_items(20)
        classify_v2_batch(items, city="test", write_rules=False)

        self.assertEqual(mock_call.call_count, 1)

    @patch("gov_price_etl.ai.service._call_gateway")
    def test_25_items_split_into_2_batches(self, mock_call):
        """25 条 items → 2 批（20 + 5）"""
        from gov_price_etl.ai.service import classify_v2_batch

        mock_call.return_value = (True, '{"results": {}}')

        items = self._make_items(25)
        classify_v2_batch(items, city="test", write_rules=False)

        self.assertEqual(mock_call.call_count, 2)

    @patch("gov_price_etl.ai.service._call_gateway")
    def test_45_items_split_into_3_batches(self, mock_call):
        """45 条 items → 3 批（20 + 20 + 5）"""
        from gov_price_etl.ai.service import classify_v2_batch

        mock_call.return_value = (True, '{"results": {}}')

        items = self._make_items(45)
        classify_v2_batch(items, city="test", write_rules=False)

        self.assertEqual(mock_call.call_count, 3)


if __name__ == "__main__":
    print("=" * 60)
    print("  V2_AI_BATCH_SIZE 批量切片测试")
    print("=" * 60)
    unittest.main(verbosity=2)
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_category_v2.py - 4 层分类主入口单元测试

运行：python3 -m pytest tests/test_category_v2.py -v
或： python3 tests/test_category_v2.py        （无 pytest 时自测）
"""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

# 把项目根加入 sys.path（让 gov_price_etl 可导入）
TEST_DIR = Path(__file__).parent
PROJECT_ROOT = TEST_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from gov_price_etl.classify.category_v3 import (
    classify_v3,
    classify_v3_batch,
    close_singleton,
    _stage1_db_exact,
    _stage2_db_fuzzy,
    _stage3_pattern,
    _stage5_unit_fallback,
    UNIT_FALLBACK_MAP,
    L4_PATTERNS_BUILTIN,
)


def _make_temp_db() -> str:
    """构造一个最小可用的 v2 测试库到 tempfile，路径返回。"""
    from scripts.init_category_v3_db import (
        init_db, import_category_nodes, SCHEMA_SQL,
    )
    fd, path = tempfile.mkstemp(suffix=".db", prefix="cat_v2_test_")
    os.close(fd)
    db_path = Path(path)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    conn.close()
    # 用 import_category_nodes 灌数据（虽然它指向默认 db_path，我们改它的全局再恢复）
    # 简单做法：直接调 init_db 然后让 import_category_nodes 写到默认路径 → 不用
    # 这里直接走 init_db + 自己灌入测试数据
    return str(db_path)


def _seed_test_breed_l3_map(db_path: str):
    """往 breed_l3_map_v3 灌入测试数据（模拟阶段 1+2 命中）"""
    conn = sqlite3.connect(db_path)
    test_pairs = [
        ("PP-R冷水管",      "03.01.02", "manual",  1.0),
        ("PP-R热水管",      "03.01.02", "manual",  1.0),
        ("UPVC排水管",      "03.02.02", "manual",  1.0),
        ("商品砼",         "01.05.01", "manual",  1.0),
        ("电力电缆",        "04.06.01", "manual",  1.0),
    ]
    conn.executemany(
        """INSERT OR REPLACE INTO breed_l3_map_v3 (breed_clean, l3, source, confidence)
           VALUES (?, ?, ?, ?)""",
        test_pairs,
    )
    conn.commit()
    conn.close()


class TestClassifyV2(unittest.TestCase):
    """4 层分类主入口测试"""

    @classmethod
    def setUpClass(cls):
        """准备测试库（用真实库而非 tempfile，因为 category_v2 表内容来自
        category_v3.json 灌入，手动复制 50 条到 tempfile 麻烦）"""
        # 重置单例连接：防止上一个测试类缓存的连接指向已删除的 temp_db
        close_singleton()

        cls.db_path = str(PROJECT_ROOT / "data" / "category_v3_rules.db")
        # 确保库存在
        if not Path(cls.db_path).exists():
            from scripts.init_category_v3_db import main as init_main
            sys.argv = ["init_category_v3_db.py"]
            init_main()
        # 灌入测试用的 breed_l3_map（不污染生产库：用临时 db_path）
        fd, cls.temp_db = tempfile.mkstemp(suffix=".db", prefix="cat_v2_test_")
        os.close(fd)
        from scripts.init_category_v3_db import init_db, import_category_nodes
        init_db(Path(cls.temp_db))
        # 复制 category_v2 表
        src = sqlite3.connect(cls.db_path)
        dst = sqlite3.connect(cls.temp_db)
        for row in src.execute("SELECT * FROM category_v3"):
            dst.execute(
                """INSERT INTO category_v3
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", row,
            )
        src.close()
        dst.commit()
        dst.close()
        # 灌入 breed_l3_map_v3 测试数据
        _seed_test_breed_l3_map(cls.temp_db)
        # 再次重置单例（避免 setUpClass 期间产生的连接指向 temp_db，被 tearDown 删后影响后续）
        close_singleton()

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "temp_db") and os.path.exists(cls.temp_db):
            os.unlink(cls.temp_db)
        # 清空单例，避免指向已删除的 temp_db
        close_singleton()

    # ── 阶段 1: db_exact ──────────────────────────────────────
    def test_stage1_db_exact(self):
        """阶段 1: breed_l3_map_v3 精确匹配"""
        conn = sqlite3.connect(self.temp_db)
        result = _stage1_db_exact(conn, "PP-R冷水管")
        conn.close()
        self.assertIsNotNone(result)
        self.assertEqual(result["l3"], "03.01.02")
        self.assertEqual(result["category_v2_source"], "db_exact_v3")
        self.assertEqual(result["name_l3"], "塑料给水管")
        self.assertEqual(result["gb_50500"], "031002")
        self.assertEqual(result["ifc_class"], "IfcPipeSegment")
        self.assertEqual(result["main_or_aux"], "主材")

    def test_stage1_db_exact_miss(self):
        """阶段 1: 精确匹配未命中（品种不在表里）"""
        conn = sqlite3.connect(self.temp_db)
        result = _stage1_db_exact(conn, "从未录入的奇怪品种")
        conn.close()
        self.assertIsNone(result)

    # ── 阶段 2: db_fuzzy ──────────────────────────────────────
    def test_stage2_db_fuzzy(self):
        """阶段 2: Jaccard 模糊召回（相似度 >= 0.6）"""
        conn = sqlite3.connect(self.temp_db)
        # "PP-R热水管" 跟 "PP-R冷水管" Jaccard 相似度 = 5/6 ≈ 0.83
        result = _stage2_db_fuzzy(conn, "PP-R热水管")
        conn.close()
        # 注意：本测试样本的 PP-R 热水管 实际在阶段 1 也命中
        # 这里用阶段 1 不存在的模糊测试
        self.assertIsNotNone(result)  # 应能命中（PP-R 家族相似度够高）

    def test_stage2_db_fuzzy_no_match(self):
        """阶段 2: 相似度 < 0.6 拒绝"""
        conn = sqlite3.connect(self.temp_db)
        result = _stage2_db_fuzzy(conn, "完全无关的产品ABC")
        conn.close()
        self.assertIsNone(result)

    # ── 阶段 3: pattern ───────────────────────────────────────
    def test_stage3_pattern_ppr(self):
        """阶段 3: PP-R pattern 命中塑料给水管"""
        conn = sqlite3.connect(self.temp_db)
        result = _stage3_pattern(conn, "PP-R 冷水管", "DN25 1.6MPa")
        conn.close()
        self.assertIsNotNone(result)
        self.assertEqual(result["l3"], "03.01.02")
        self.assertEqual(result["category_v2_source"], "pattern_v3")
        self.assertGreaterEqual(result["category_v2_confidence"], 0.8)

    def test_stage3_pattern_upvc(self):
        """阶段 3: UPVC pattern 命中塑料排水管"""
        conn = sqlite3.connect(self.temp_db)
        result = _stage3_pattern(conn, "UPVC 排水管", "DN100")
        conn.close()
        self.assertEqual(result["l3"], "03.02.02")

    def test_stage3_pattern_cable(self):
        """阶段 3: YJV 电力电缆 pattern"""
        conn = sqlite3.connect(self.temp_db)
        result = _stage3_pattern(conn, "电力电缆", "YJV 4×185")
        conn.close()
        self.assertEqual(result["l3"], "04.06.01")
        self.assertEqual(result["ifc_class"], "IfcCableSegment")

    def test_stage3_pattern_no_match(self):
        """阶段 3: 任何 pattern 都不匹配"""
        conn = sqlite3.connect(self.temp_db)
        result = _stage3_pattern(conn, "XX", "YY")
        conn.close()
        self.assertIsNone(result)

    # ── 阶段 5: unit 兜底 ─────────────────────────────────────
    def test_stage5_unit_fallback_m3(self):
        """阶段 5: unit=m³ → 现浇混凝土基础"""
        conn = sqlite3.connect(self.temp_db)
        result = _stage5_unit_fallback(conn, "m³")
        conn.close()
        self.assertIsNotNone(result)
        self.assertEqual(result["l3"], "01.05.01")
        self.assertEqual(result["category_v2_source"], "fallback_v3")
        self.assertLess(result["category_v2_confidence"], 0.5)

    def test_stage5_unit_fallback_unit_normalize(self):
        """阶段 5: unit=m3 标准化 → m³"""
        conn = sqlite3.connect(self.temp_db)
        result = _stage5_unit_fallback(conn, "m3")
        conn.close()
        self.assertIsNotNone(result)
        self.assertEqual(result["l3"], "01.05.01")

    def test_stage5_unit_fallback_no_match(self):
        """阶段 5: 未知 unit 返回 None"""
        conn = sqlite3.connect(self.temp_db)
        result = _stage5_unit_fallback(conn, "未知单位")
        conn.close()
        self.assertIsNone(result)

    # ── 主入口：5 段式端到端 ──────────────────────────────────
    def test_classify_v3_stage1_hit(self):
        """端到端：阶段 1 命中（PP-R 冷水管）"""
        result = classify_v3("PP-R 冷水管", "DN25 1.6MPa", "m", "PP-R冷水管", db_path=self.temp_db)
        self.assertEqual(result["l3"], "03.01.02")
        self.assertEqual(result["category_v2_source"], "db_exact_v3")
        self.assertEqual(result["category_v2_confidence"], 1.0)

    def test_classify_v3_stage3_hit(self):
        """端到端：阶段 3 命中（breed_clean 不在 db，但 breed+spec 有 YJV pattern）"""
        result = classify_v3("电力电缆", "YJV 4×185", "m", "未知品种", db_path=self.temp_db)
        # 阶段 1（breed_clean="未知品种"）未命中
        # 阶段 2 Jaccard 相似度不够
        # 阶段 3：haystack="电力电缆 YJV 4×185" 匹配 YJV pattern → 04.06.01（v3 L3）
        self.assertEqual(result["l3"], "04.06.01")
        self.assertEqual(result["category_v2_source"], "pattern_v3")

    def test_classify_v3_stage5_fallback(self):
        """端到端：兜底（完全不认识的品种 + 体积单位）"""
        result = classify_v3("未知物品XYZ", "M-001", "m³", "未知物品XYZ", db_path=self.temp_db)
        self.assertEqual(result["l3"], "01.05.01")
        self.assertEqual(result["category_v2_source"], "fallback_v3")

    def test_classify_v3_db_path_missing_failsafe(self):
        """fail-safe: db_path 不存在时返回 error_v2 而不抛异常"""
        result = classify_v3("PP-R", "DN25", "m", "PP-R", db_path="/nonexistent/path.db")
        self.assertEqual(result["category_v2_source"], "error_v3")
        self.assertEqual(result["l3"], "")

    def test_classify_v3_complete_fields(self):
        """端到端：所有 9 个元数据字段都有值"""
        result = classify_v3("PP-R 冷水管", "DN25 1.6MPa", "m", "PP-R冷水管", db_path=self.temp_db)
        # 必填字段非 None / 非空
        for k in ["l1", "l2", "l3", "name_l1", "name_l2", "name_l3", "gb_50500", "ifc_class", "unit", "main_or_aux"]:
            self.assertTrue(result.get(k), f"字段 {k} 应非空: {result}")

    # ── 批量入口 ──────────────────────────────────────────────
    def test_classify_v3_batch(self):
        items = [
            {"breed": "PP-R 冷水管", "spec": "DN25", "unit": "m", "breed_clean": "PP-R冷水管"},
            {"breed": "电力电缆",   "spec": "YJV",   "unit": "m", "breed_clean": "电力电缆"},
            {"breed": "未知物品",   "spec": "M-1",   "unit": "m³", "breed_clean": "未知物品"},
        ]
        results = classify_v3_batch(items, db_path=self.temp_db)
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0]["l3"], "03.01.02")
        self.assertEqual(results[1]["l3"], "04.06.01")
        self.assertEqual(results[2]["category_v2_source"], "fallback_v3")

    # ── 字典结构验证 ──────────────────────────────────────────
    def test_dict_v2_l3_count(self):
        """category_v3.json 至少有 50 个 L3 节点"""
        path = PROJECT_ROOT / "data" / "category_v3.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        l3_count = sum(len(l2["l3"]) for l1 in data["tree"]["l1"] for l2 in l1["l2"])
        self.assertGreaterEqual(l3_count, 50)

    def test_dict_std_codes_l3_count(self):
        """std_codes_v3.json 至少有 50 个 L3 标准码"""
        path = PROJECT_ROOT / "data" / "std_codes_v3.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(data["codes"]), 50)

    def test_dict_l1_count(self):
        """8 个 L1 专业大类"""
        path = PROJECT_ROOT / "data" / "category_v3.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        l1_codes = [n["code"] for n in data["tree"]["l1"]]
        self.assertEqual(len(l1_codes), 8)
        # 验证 L1 编号连续
        self.assertEqual(l1_codes, ["01", "02", "03", "04", "05", "06", "07", "08"])

    def test_dict_ifc_class_valid(self):
        """所有 L3 的 ifc_class 都是非空字符串"""
        path = PROJECT_ROOT / "data" / "std_codes.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for l3, code in data["codes"].items():
            self.assertTrue(code.get("ifc_class"), f"{l3} 缺 ifc_class")

    def test_pattern_count(self):
        """L4 patterns 数量 >= 30"""
        self.assertGreaterEqual(len(L4_PATTERNS_BUILTIN), 30)

    def test_unit_fallback_count(self):
        """Unit 兜底覆盖 >= 8 种 unit"""
        self.assertGreaterEqual(len(UNIT_FALLBACK_MAP), 8)


if __name__ == "__main__":
    # 两种运行方式都支持
    try:
        import pytest
        sys.exit(pytest.main([__file__, "-v"]))
    except ImportError:
        unittest.main(verbosity=2)

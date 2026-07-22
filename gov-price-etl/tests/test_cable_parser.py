"""test_cable_parser.py - ETL cable GB/T 12706 解析器单元测试 (v0.10, 2026-07-22)

覆盖:
  - is_cable_breed: breed 关键词命中
  - parse_cable_spec: 6 类典型 spec 解析
  - get_parser wrapper: cable 路径纯净 / 非 cable 走 base / fallback
  - attr_utils 三道加固: forbidden_keys / forbidden_pairs / desc_words
  - base.py catch-all 禁填: volume/package_type 永不写入
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import unittest
from gov_price_etl.parse_spec.cable import (
    is_cable_breed,
    parse_cable_spec,
    clear_cache as cable_clear_cache,
)
from gov_price_etl.parse_spec import get_parser
from gov_price_etl.transform.attr_utils import (
    sanitize_attr,
    clear_cache,
    _load_attr_filters,
)


class TestIsCableBreed(unittest.TestCase):
    def setUp(self):
        cable_clear_cache()

    def test_cable_breeds(self):
        for b in ["电力电缆", "控制电缆", "信号电缆", "通信电缆",
                  "铜芯电缆", "高压电缆", "矿物电缆", "电线"]:
            self.assertTrue(is_cable_breed(b), f"{b} 应该是 cable")

    def test_non_cable_breeds(self):
        for b in ["螺纹钢", "圆钢", "铝合金型材", "C30混凝土", "油漆"]:
            self.assertFalse(is_cable_breed(b), f"{b} 不应该是 cable")

    def test_empty_breed(self):
        self.assertFalse(is_cable_breed(""))


class TestParseCableSpec(unittest.TestCase):
    def setUp(self):
        cable_clear_cache()

    def test_yjv_basic(self):
        r = parse_cable_spec("YJV-0.6/1kV-3*2.5mm2", "电力电缆")
        self.assertEqual(r["type"], "YJV")
        self.assertEqual(r["voltage"], "0.6/1kV")
        self.assertEqual(r["core_count"], 3)
        self.assertEqual(r["cross_section"], "2.5mm²")

    def test_vv_basic(self):
        r = parse_cable_spec("VV-0.6/1kV-4*4", "电力电缆")
        self.assertEqual(r["type"], "VV")
        self.assertEqual(r["core_count"], 4)

    def test_yjv22_armor(self):
        r = parse_cable_spec("YJV22-8.7/15KV-3*50mm2", "电力电缆")
        self.assertEqual(r["type"], "YJV22")
        self.assertEqual(r["voltage"], "8.7/15kV")
        self.assertEqual(r["armor_type"], "钢带铠装")

    def test_za_yjv22_fire(self):
        r = parse_cable_spec("ZA-YJV22-8.7/15KV-3*300mm2", "电力电缆")
        self.assertEqual(r["type"], "YJV22")
        self.assertEqual(r["fire_rating"], "A级阻燃")
        self.assertEqual(r["armor_type"], "钢带铠装")

    def test_wdzn_yjfe(self):
        r = parse_cable_spec("WDZN-YJ(F)E-0.6/1kV-4*4", "电力电缆")
        self.assertEqual(r["type"], "YJ(F)E")
        self.assertEqual(r["fire_rating"], "低烟无卤阻燃耐火")

    def test_kvv_control(self):
        r = parse_cable_spec("KVV-450/750V-4*1.5mm2", "控制电缆")
        self.assertEqual(r["type"], "KVV")
        self.assertEqual(r["voltage"], "450/750V")
        self.assertEqual(r["core_count"], 4)

    def test_no_match_returns_empty(self):
        r = parse_cable_spec("综合", "电力电缆")
        self.assertEqual(r, {})

    def test_empty_spec(self):
        self.assertEqual(parse_cable_spec("", "电力电缆"), {})

    def test_voltage_kv_canonical(self):
        r = parse_cable_spec("YJV22-8.7/15KV-3*50mm2", "电力电缆")
        self.assertEqual(r["voltage"], "8.7/15kV")  # KV → kV


class TestCableAwareParser(unittest.TestCase):
    def setUp(self):
        cable_clear_cache()

    def test_cable_breed_returns_pure_cable_attrs(self):
        """cable breed 时 wrapper 应只返回 cable attrs, 不带 base parser 噪声。"""
        p = get_parser("xian")
        r = p.parse("YJV-0.6/1kV-3*2.5mm2", "电力电缆", "", "")
        self.assertEqual(r["type"], "YJV")
        self.assertEqual(r["voltage"], "0.6/1kV")
        self.assertEqual(r["core_count"], 3)
        self.assertEqual(r["cross_section"], "2.5mm²")
        # 不应有 base parser 的噪声
        for noise_key in ["material", "diameter", "thickness"]:
            self.assertNotIn(noise_key, r, f"cable 路径不应有 {noise_key}")

    def test_non_cable_breed_uses_base(self):
        """非 cable breed 走 base parser 原逻辑。"""
        p = get_parser("xian")
        r = p.parse("Φ20*9m", "螺纹钢", "", "")
        self.assertIn("diameter", r)
        self.assertIn("thickness", r)

    def test_cable_breed_no_match_falls_back_to_base(self):
        """cable breed 但 spec 不匹配命名规则 → fallback base parser。"""
        p = get_parser("xian")
        r = p.parse("综合", "电力电缆", "", "")
        # base parser 会兜底 (catch-all 拦截后) — 至少不应崩
        self.assertIsInstance(r, dict)


class TestAttrUtilsThreeHardening(unittest.TestCase):
    """测试 transform/attr_utils.py 三道加固 (Step 9)。"""

    def setUp(self):
        clear_cache()

    def test_forbidden_keys_volume(self):
        self.assertNotIn("volume", sanitize_attr({"volume": "60m³"}))

    def test_forbidden_keys_package_type(self):
        self.assertNotIn("package_type", sanitize_attr({"package_type": "mm"}))

    def test_forbidden_pairs_brand_dn(self):
        for bad in ["DN", "FN", "PC", "PE", "PP", "PVC"]:
            self.assertEqual(sanitize_attr({"brand": bad}), {}, f"brand={bad} 应被拒")

    def test_material_desc_words(self):
        for desc in ["厚", "板材厚度", "强度等级", "供电", "流体管"]:
            self.assertEqual(sanitize_attr({"material": desc}), {}, f"material={desc} 应被拒")

    def test_legitimate_attrs_kept(self):
        r = sanitize_attr({"diameter": "28mm", "material": "Q235B", "grade": "HRB400"})
        self.assertEqual(len(r), 3)

    def test_load_attr_filters(self):
        rules = _load_attr_filters()
        self.assertIn("forbidden_keys", rules)
        self.assertIn("forbidden_pairs", rules)
        self.assertIn("desc_words_for_material", rules)


if __name__ == "__main__":
    unittest.main(verbosity=2)
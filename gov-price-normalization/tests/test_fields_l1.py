"""test_fields_l1.py — L1 fields 层单元测试 (v0.2, 2026-07-22)

覆盖：
  - sanitize_attr 各类脏数据模式
  - normalize_cable_type GB/T 12706 命名反解
  - pipeline 串联 L1 → L3 → L2
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import unittest
from gov_price_normalization.layers import fields
from gov_price_normalization.pipeline import normalize_doc


class TestSanitizeAttr(unittest.TestCase):
    """测试 sanitize_attr 的 10 个脏数据规则。"""

    def setUp(self):
        fields.clear_cache()

    def test_forbidden_key_volume(self):
        """volume 字段应被删 (sichuan 12 万条主要来源)。"""
        doc = {"attr": [{"k": "volume", "v": "60m³"}, {"k": "thickness", "v": "60mm"}]}
        r = fields.sanitize_attr(doc)
        keys = [a["k"] for a in r["attr_norm"]]
        self.assertNotIn("volume", keys)
        self.assertIn("thickness", keys)
        self.assertIn(("volume", "60m³"), [(d[0], d[1]) for d in r["dropped"]])

    def test_forbidden_key_package_type(self):
        """package_type='mm' 纯单位词应被删 (qinghai 13k 条)。"""
        doc = {"attr": [{"k": "package_type", "v": "mm"}]}
        r = fields.sanitize_attr(doc)
        self.assertEqual(r["attr_norm"], [])
        self.assertEqual(len(r["dropped"]), 1)

    def test_forbidden_pair_brand_dn(self):
        """brand=DN/FN/PC/PE/PP/PVC 黑名单应被删 (shanxi 493 条)。"""
        for bad in ["DN", "FN", "PC", "PE", "PP", "PVC", "Dn", "dn"]:
            doc = {"attr": [{"k": "brand", "v": bad}]}
            r = fields.sanitize_attr(doc)
            self.assertEqual(r["attr_norm"], [], f"brand={bad} 应被删")

    def test_material_desc_word(self):
        """material 出现描述词 (厚/长/高/直径) 应被删 (8k 条)。"""
        for desc in ["厚", "板材厚度", "强度等级", "供电", "流体管", "直径"]:
            doc = {"attr": [{"k": "material", "v": desc}]}
            r = fields.sanitize_attr(doc)
            self.assertEqual(r["attr_norm"], [], f"material={desc} 应被删")

    def test_promote_height_min(self):
        """height_min → height_range (chongqing 3.8k 条)。"""
        doc = {"attr": [{"k": "height_min", "v": "80cm"}, {"k": "pressure", "v": "100MPa"}]}
        r = fields.sanitize_attr(doc)
        promoted = [(p["k"], p["v"]) for p in r["promoted"]]
        self.assertIn(("height_range", "80cm"), promoted)
        self.assertIn(("pressure", "100MPa"), [(a["k"], a["v"]) for a in r["attr_norm"]])

    def test_promote_cross_section_area(self):
        """cross_section_area → cross_section (18k 条)。"""
        doc = {"attr": [{"k": "cross_section_area", "v": "20mm²"}]}
        r = fields.sanitize_attr(doc)
        self.assertEqual(r["attr_norm"], [{"k": "cross_section", "v": "20mm²"}])

    def test_promote_mix_grade(self):
        """mix_grade 是合理字段, 保留 (8.2k 条 qinghai)。"""
        doc = {"attr": [{"k": "mix_grade", "v": "M7.5"}]}
        r = fields.sanitize_attr(doc)
        self.assertEqual(r["attr_norm"], [{"k": "mix_grade", "v": "M7.5"}])

    def test_promote_particle_size(self):
        """particle_size 是合理字段, 保留 (shaanxi 碎 0.5~1.5cm)。"""
        doc = {"attr": [{"k": "particle_size", "v": "0.5~1.5cm"}]}
        r = fields.sanitize_attr(doc)
        self.assertEqual(r["attr_norm"], [{"k": "particle_size", "v": "0.5~1.5cm"}])

    def test_numeric_required_no_digit(self):
        """数值字段无数字应被删。"""
        doc = {"attr": [{"k": "thickness", "v": "厚度"}, {"k": "thickness", "v": "30mm"}]}
        r = fields.sanitize_attr(doc)
        self.assertEqual(r["attr_norm"], [{"k": "thickness", "v": "30mm"}])

    def test_empty_attr(self):
        """空 attr 应标 empty=True, attr_norm=[] (86k 孤儿)。"""
        for empty in [None, [], []]:
            doc = {"attr": empty}
            r = fields.sanitize_attr(doc)
            self.assertTrue(r["empty"])
            self.assertEqual(r["attr_norm"], [])

    def test_empty_kv(self):
        """缺 k 或 v 应被删。"""
        doc = {"attr": [{"k": "", "v": "100mm"}, {"k": "thickness", "v": ""}, {"k": None, "v": "x"}]}
        r = fields.sanitize_attr(doc)
        self.assertEqual(r["attr_norm"], [])

    def test_legitimate_attrs_kept(self):
        """合理 attr 应全部保留 (sanity check)。"""
        doc = {"attr": [
            {"k": "diameter", "v": "28mm"},
            {"k": "material", "v": "Q235B"},
            {"k": "grade", "v": "HRB400"},
            {"k": "core_count", "v": "3"},
            {"k": "color", "v": "红色"},
        ]}
        r = fields.sanitize_attr(doc)
        self.assertEqual(len(r["attr_norm"]), 5)
        self.assertEqual(r["dropped"], [])


class TestNormalizeCableType(unittest.TestCase):
    """测试 GB/T 12706 电缆命名反解。"""

    def setUp(self):
        fields.clear_cache()

    def test_yjv_basic(self):
        """YJV-0.6/1kV-3*2.5mm2 → type=YJV, voltage=0.6/1kV, core=3, section=2.5mm²"""
        doc = {"breed": "电力电缆", "spec": "YJV-0.6/1kV-3*2.5mm2"}
        r = fields.normalize_cable_type(doc)
        self.assertTrue(r["applied"])
        self.assertEqual(r["canonical_type"], "YJV")
        self.assertEqual(r["voltage"], "0.6/1kV")
        self.assertEqual(r["core_count"], 3)
        self.assertEqual(r["cross_section"], "2.5mm²")
        self.assertIsNone(r["fire_rating"])
        self.assertIsNone(r["armor_type"])
        self.assertEqual(r["drop_keys"], ["type"])

    def test_vv_basic(self):
        doc = {"breed": "电力电缆", "spec": "VV-0.6/1kV-4*4"}
        r = fields.normalize_cable_type(doc)
        self.assertTrue(r["applied"])
        self.assertEqual(r["canonical_type"], "VV")
        self.assertEqual(r["core_count"], 4)
        self.assertEqual(r["cross_section"], "4mm²")

    def test_yjv22_armor(self):
        """YJV22-8.7/15KV-3*50mm2 → type=YJV22, voltage=8.7/15kV, armor=钢带铠装"""
        doc = {"breed": "电力电缆", "spec": "YJV22-8.7/15KV-3*50mm2"}
        r = fields.normalize_cable_type(doc)
        self.assertTrue(r["applied"])
        self.assertEqual(r["canonical_type"], "YJV22")
        self.assertEqual(r["voltage"], "8.7/15kV")
        self.assertEqual(r["core_count"], 3)
        self.assertEqual(r["cross_section"], "50mm²")
        self.assertEqual(r["armor_type"], "钢带铠装")

    def test_za_yjv22(self):
        """ZA-YJV22-8.7/15KV-3*300mm2 → fire_rating=A级阻燃"""
        doc = {"breed": "铜芯高压电力电缆", "spec": "ZA-YJV22-8.7/15KV-3*300mm2"}
        r = fields.normalize_cable_type(doc)
        self.assertTrue(r["applied"])
        self.assertEqual(r["canonical_type"], "YJV22")
        self.assertEqual(r["fire_rating"], "A级阻燃")

    def test_wdzn_yjfe(self):
        """WDZN-YJ(F)E-0.6/1kV-4*4 → type=YJ(F)E (含括号), fire_rating=低烟无卤阻燃耐火"""
        doc = {"breed": "电力电缆", "spec": "WDZN-YJ(F)E-0.6/1kV-4*4"}
        r = fields.normalize_cable_type(doc)
        self.assertTrue(r["applied"])
        self.assertEqual(r["canonical_type"], "YJ(F)E")
        self.assertEqual(r["fire_rating"], "低烟无卤阻燃耐火")

    def test_kvv_control_cable(self):
        """KVV-450/750V-4*1.5mm2 → type=KVV, voltage=450/750V"""
        doc = {"breed": "控制电缆", "spec": "KVV-450/750V-4*1.5mm2"}
        r = fields.normalize_cable_type(doc)
        self.assertTrue(r["applied"])
        self.assertEqual(r["canonical_type"], "KVV")
        self.assertEqual(r["voltage"], "450/750V")
        self.assertEqual(r["core_count"], 4)

    def test_voltage_canonic(self):
        """KV 大写应规范化为 kV。"""
        doc = {"breed": "电力电缆", "spec": "YJV22-8.7/15KV-3*50mm2"}
        r = fields.normalize_cable_type(doc)
        self.assertEqual(r["voltage"], "8.7/15kV")

    def test_not_cable_breed(self):
        """非电缆 breed 应不应用。"""
        doc = {"breed": "螺纹钢", "spec": "Φ20*9m"}
        r = fields.normalize_cable_type(doc)
        self.assertFalse(r["applied"])

    def test_no_spec(self):
        """无 spec 应不应用。"""
        doc = {"breed": "电力电缆", "spec": ""}
        r = fields.normalize_cable_type(doc)
        self.assertFalse(r["applied"])

    def test_no_match(self):
        """不匹配命名规则的 spec 应跳过。"""
        doc = {"breed": "电力电缆", "spec": "综合"}
        r = fields.normalize_cable_type(doc)
        self.assertFalse(r["applied"])


class TestPipelineIntegration(unittest.TestCase):
    """测试 L1 + L3 + L2 串联。"""

    def setUp(self):
        fields.clear_cache()

    def test_cable_doc_full_pipeline(self):
        """完整 pipeline 处理脏数据电缆 doc。"""
        doc = {
            "_id": "test_001",
            "breed": "电力电缆",
            "spec": "YJV-0.6/1kV-3*2.5mm2",
            "unit": "m",
            "price": 100.0,
            "period_start": "2026-02-15",
            "attr": [
                {"k": "type", "v": "YJV-0"},          # 错的截断
                {"k": "core_count", "v": "3"},
                {"k": "material", "v": "2"},            # 数字误填材质
                {"k": "volume", "v": "2.5m³"},         # 错的体积
                {"k": "thickness", "v": "2mm"},
            ],
        }
        out = normalize_doc(doc, "xian", l3_code="04.05.07")
        # L1 删脏
        attr_norm_keys = [a["k"] for a in out["attr_norm"]]
        self.assertNotIn("volume", attr_norm_keys)
        self.assertNotIn("type", attr_norm_keys)
        self.assertIn("core_count", attr_norm_keys)
        # thickness 不在电缆 (04.05.07) L3 白名单 allow, 被白名单拒
        self.assertNotIn("thickness", attr_norm_keys)
        self.assertTrue(any(d[0] == "thickness" and "l3_not_in_allow" in d[2] for d in out["_norm"]["dropped_attrs"]))
        # cable canonical 写入
        self.assertIn("canonical_type", attr_norm_keys)
        self.assertEqual(
            next(a["v"] for a in out["attr_norm"] if a["k"] == "canonical_type"),
            "YJV",
        )
        # L3 正常
        self.assertEqual(out["canonical_period"], "2026-02")
        # status
        self.assertEqual(out["_norm"]["status"]["L1_attr_sanitize"], "ok")
        self.assertEqual(out["_norm"]["status"]["L1_cable_canonical"], "ok")
        # dropped 留痕
        dropped = out["_norm"]["dropped_attrs"]
        self.assertTrue(any(d[0] == "type" for d in dropped))
        self.assertTrue(any(d[0] == "volume" for d in dropped))

    def test_empty_attr_doc(self):
        """空 attr 文档（孤儿）应正常处理，不报错。"""
        doc = {
            "breed": "螺纹钢",
            "spec": "Φ20",
            "unit": "kg",
            "price": 5.0,
            "period_start": "2026-02-15",
            "attr": [],
        }
        out = normalize_doc(doc, "xian")
        self.assertEqual(out["attr_norm"], [])
        self.assertEqual(out["_norm"]["status"]["L1_attr_sanitize"], "skipped_empty")

    def test_non_cable_doc(self):
        """非电缆 doc 不触发 cable canonical。"""
        doc = {
            "breed": "螺纹钢",
            "spec": "Φ20",
            "unit": "kg",
            "price": 5.0,
            "period_start": "2026-02-15",
            "attr": [{"k": "diameter", "v": "20mm"}],
        }
        out = normalize_doc(doc, "xian")
        self.assertEqual(out["attr_norm"], [{"k": "diameter", "v": "20mm"}])
        self.assertNotIn("L1_cable_canonical", out["_norm"]["status"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
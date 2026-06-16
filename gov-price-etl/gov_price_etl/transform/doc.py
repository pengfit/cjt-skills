"""transform/doc.py - 单文档 ODS → DWD 转换

职责：
  - transform_doc()  把一条 ODS 原始文档清洗为 DWD 格式

v1 清理（2026-06-16）：
  - 不再调 v1 AI（classify_breed_batch 已删除）
  - DWD.category 字段值 = v2 L1 中文名（如"建筑工程"）
    —— 用于 spec 规则库过滤（v1 大类已迁移到 v2 L1 名）
  - DWD 14 个 v2 字段保留完整（l1/l2/l3/l4 + name + 7 属性 + 4 标准码）
"""
from datetime import datetime

from gov_price_etl.classify.category_v2 import classify_v2
from gov_price_etl.parse_spec import get_parser
from gov_price_etl.transform.clean import clean_breed, clean_unit, clean_price


def transform_doc(raw: dict, source_index: str, city: str) -> dict:
    """将一条 ODS 原始文档清洗为 DWD 格式。

    字段：
      - breed / breed_clean / spec / unit / price / tax_price
      - category = v2 L1 中文名（如"建筑工程"），用于 spec 规则库过滤
      - 4 层 v2 分类：category_l1 / l2 / l3 / l4
      - 工程属性：eng_part / eng_stage / main_or_aux
      - 标准码：gb_50500 / quota_ref / ifc_class / uniclass_ss
      - 物料视图：material_code
      - v2 元信息：category_v2_source / category_v2_confidence
      - province / city / county / tab_type / tab_name
      - update_date / publish_time / period / code / source
      - citywide_category / source_index / etl_time
      - attr（nested list of {k, v}）
    """
    breed_raw = raw.get("breed", "")
    spec_raw = raw.get("spec", "")
    unit_raw = raw.get("unit", "")

    breed_clean = clean_breed(breed_raw)
    spec_clean = spec_raw
    unit_clean = clean_unit(unit_raw)

    # ── v2 4 层分类（唯一分类源）──
    # 走模块级单例 SQLite 连接，性能 ~0.05ms/次。
    # fail-safe：库文件不存在/异常时返回空 v2 字段。
    v2 = classify_v2(
        breed=breed_raw,
        spec=spec_clean,
        unit=unit_clean,
        breed_clean=breed_clean,
    )
    # DWD.category = v2 L1 中文名（spec 规则库按此过滤，11,061 条规则已迁到 v2 L1 名）
    category = v2.get("name_l1") or ""

    price = clean_price(raw.get("price")) or 0.0
    tax_price = clean_price(raw.get("tax_price")) or 0.0
    # Crawler bug: when is_tax="0" (不含税), wrote 不含税价 to tax_price, left price=0
    # Fix: if price==0 but tax_price has value, use tax_price as the price
    if price == 0.0 and tax_price > 0:
        price = tax_price
        tax_price = 0.0

    parser = get_parser(city)
    # breed_raw 用于查规则库（规则里存的是原始格式），breed_clean 用于分类/展示
    spec_parsed = parser.parse(spec_clean, breed_raw, category)
    if not spec_parsed:
        # 回退：用 clean_breed 再查一次（部分规则可能用 clean 格式录入）
        spec_parsed = parser.parse(spec_clean, breed_clean, category)

    flat_attr = {k: v for k, v in spec_parsed.items() if v}
    # DWD 统一用 nested attr 格式存储，与 DWS 保持一致
    nested_attr = [{"k": k, "v": v} for k, v in flat_attr.items()]

    return {
        "breed": breed_raw,
        "breed_clean": breed_clean,
        "spec": spec_clean,
        "unit": unit_clean,
        "price": price,
        "tax_price": tax_price,
        "category": category,                                # v1 一级分类（保留兼容）
        "category_l1":     v2.get("l1", ""),                # v2 4 层分类
        "category_l2":     v2.get("l2", ""),
        "category_l3":     v2.get("l3", ""),
        "category_l4":     v2.get("l4", "UNCLASSIFIED"),
        "category_name_l1": v2.get("name_l1", ""),          # L1 中文名（如"建筑工程"）—— 前缀统一 category_
        "category_name_l2": v2.get("name_l2", ""),          # L2 中文名
        "category_name_l3": v2.get("name_l3", ""),          # L3 中文名
        "eng_part":        v2.get("eng_part") or "",        # 工程部位
        "eng_stage":       v2.get("eng_stage") or "",        # 工程阶段（多选用逗号分隔）
        "main_or_aux":     v2.get("main_or_aux") or "",      # 主材/辅材
        "gb_50500":        v2.get("gb_50500") or "",         # GB 50500 清单项目编码
        "quota_ref":       v2.get("quota_ref") or "",        # 消耗量定额参考号
        "ifc_class":       v2.get("ifc_class") or "",        # IFC 4.3 类名
        "uniclass_ss":     v2.get("uniclass_ss") or "",      # Uniclass 2015
        "material_code":   v2.get("material_code") or "",    # 物料视图主键
        "category_v2_source":     v2.get("category_v2_source", ""),    # 5 段式来源
        "category_v2_confidence": v2.get("category_v2_confidence", 0.0),  # 0-1
        "province": raw.get("province", ""),
        "city": raw.get("city", ""),
        "county": raw.get("county", ""),
        "tab_type": raw.get("tab_type", ""),
        "tab_name": raw.get("tab_name", ""),
        "update_date": raw.get("update_date", ""),
        "publish_time": raw.get("publish_time", ""),
        "period": raw.get("period", ""),
        "code": raw.get("code", ""),
        "source": raw.get("source", ""),
        "citywide_category": raw.get("category", ""),  # 城市材料分类（建安工程材料等），区别于 classify_breed 的 category
        "source_index": source_index,
        "etl_time": datetime.now().isoformat(),
        "attr": nested_attr,
    }

"""transform/doc.py - 单文档 ODS → DWD 转换

职责：
  - transform_doc()  把一条 ODS 原始文档清洗为 DWD 格式
"""
from datetime import datetime

from gov_price_etl.classify import (
    classify_breed,
    get_category_system_map,
    get_category_system_name_map,
)
from gov_price_etl.parse_spec import get_parser
from gov_price_etl.transform.clean import clean_breed, clean_unit, clean_price


def transform_doc(raw: dict, source_index: str, city: str) -> dict:
    """将一条 ODS 原始文档清洗为 DWD 格式。

    字段：
      - breed / breed_clean / spec / unit / price / tax_price
      - category / category_system / category_system_name
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
    category = classify_breed(breed_clean, spec_clean)

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

    code_map = get_category_system_map()
    code = code_map.get(category, "")
    name_map = get_category_system_name_map()
    category_system_name = name_map.get(code, "")

    return {
        "breed": breed_raw,
        "breed_clean": breed_clean,
        "spec": spec_clean,
        "unit": unit_clean,
        "price": price,
        "tax_price": tax_price,
        "category": category,
        "category_system": code,
        "category_system_name": category_system_name,
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

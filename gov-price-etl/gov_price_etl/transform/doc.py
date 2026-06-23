"""transform/doc.py - 单文档 ODS → DWD 转换

职责：
  - transform_doc()  把一条 ODS 原始文档清洗为 DWD 格式（v2 4 层分类）

DWD 字段：
  - 基础：breed / breed_clean / spec / unit / price / tax_price
  - category = v2 L1 中文名（如"建筑工程"）—— spec 规则库按此过滤（11,061 条已迁）
  - v2 14 字段：category_l1/l2/l3/l4 + name_l1/l2/l3 + 3 工程属性 + 4 标准码 + material_code
  - v2 元信息：category_v2_source / category_v2_confidence
  - 业务：province / city / county / tab_type / tab_name / update_date / period / code / source
  - 嵌套：attr（list of {k, v}）

设计：
  - 默认走 5 段式分类（DB 优先 → 未命中兜底）
  - 支持 v2_override 外部传入（ETL 两轮 AI 场景避免重复查表）
  - spec='/' 规范化 + 空 spec 回填为 breed（与原 etl.py 逻辑一致）
"""
from datetime import datetime

from gov_price_etl.classify.category_v3 import classify_v3
from gov_price_etl.parse_spec import get_parser
from gov_price_etl.transform.clean import clean_breed, clean_unit, clean_price


def transform_doc(raw: dict, source_index: str, city: str, v2_override: dict = None) -> dict:
    """将一条 ODS 原始文档清洗为 DWD 格式。

    v2_override: 外部传入的 v2 分类结果（如 service.classify_v3_batch 返回的）。
                 为 None 时走 5 段式单条查表（阶段 4 占位 → 阶段 5 fallback）；
                 不为 None 时跳过查表直接使用（为 ETL pipeline 批量 AI 场景准备，
                 避免重复调用 classify_v3）。

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

    # ── spec 规范化（与原 etl.py 逻辑一致，迁入 transform_doc 让返回值可直接写 DWD）──
    # '/' 是 crawler 初始写入的空 spec，应规范为空
    if spec_clean == "/":
        spec_clean = ""
    # spec 为空时回填为 breed（让 spec_parsed 能查到规则）
    if not spec_clean:
        spec_clean = breed_clean or breed_raw

    # ── v2 4 层分类（唯一分类源）──
    # 走模块级单例 SQLite 连接，性能 ~0.05ms/次。
    # fail-safe：库文件不存在/异常时返回空 v2 字段。
    if v2_override is not None:
        v2 = v2_override  # 外部传入的 v2 结果（AI 批量调用等场景，避免重复查表）
    else:
        v2 = classify_v3(
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

    doc = {
        "breed": breed_raw,
        "breed_clean": breed_clean,
        "spec": spec_clean,
        "unit": unit_clean,
        "price": price,
        "tax_price": tax_price,
        "category": category,                                # v2 L1 中文名（spec 规则库过滤）
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
        # ── 时序分析字段（2026-06-23 补充，跨周期时序查询）──
        # create_time：透传 ODS（如有），fallback etl_time
        "create_time":  raw.get("create_time") or "",
        # source_publish_date：优先 create_time，fallback update_date + T00:00:00
        "source_publish_date": (
            raw.get("create_time")
            or (raw.get("update_date") + "T00:00:00" if raw.get("update_date") else "")
            or ""
        ),
        # period_granularity：ODS 已写则取 ODS，默认 monthly
        "period_granularity": raw.get("period_granularity") or "monthly",
        # period_id：源站原命名（period 或 update_date）
        "period_id":  raw.get("period_id") or raw.get("period") or raw.get("update_date") or "",
        # period_start / end / days：按 granularity 派生（与 reindex script 逻辑一致）
        "_raw_update_date": raw.get("update_date", ""),
        "_raw_period_start": raw.get("period_start", ""),
        "_raw_period_end": raw.get("period_end", ""),
        "_raw_period_days": raw.get("period_days", ""),
        "etl_time": datetime.now().isoformat(),
        "attr": nested_attr,
    }

    # 派生 period_start / end / days（如果 ODS 已有则用，否则按 update_date + granularity 派生）
    granularity = doc.get("period_granularity", "monthly")
    _ud = doc.pop("_raw_update_date", "")
    raw_ps = doc.pop("_raw_period_start", "")
    raw_pe = doc.pop("_raw_period_end", "")
    raw_pd = doc.pop("_raw_period_days", "")
    if raw_ps:
        doc["period_start"] = raw_ps
        doc["period_end"] = raw_pe or raw_ps
        doc["period_days"] = raw_pd or 30
    else:
        if _ud and len(_ud) >= 7:
            try:
                mo = int(_ud[5:7])
            except (ValueError, IndexError):
                mo = 1
            if granularity == "quarterly":
                q = (mo - 1) // 3 + 1
                sm = (q - 1) * 3 + 1
                em = q * 3
                doc["period_start"] = f"{_ud[:4]}-{sm:02d}-01"
                doc["period_end"] = f"{_ud[:4]}-{em:02d}-30"
                doc["period_days"] = 90
            else:
                # monthly: period_start = 月首, period_end = 月末, period_days = 当月天数
                last_day = 31
                if mo == 2:
                    last_day = 28
                elif mo in (4, 6, 9, 11):
                    last_day = 30
                doc["period_start"] = f"{_ud[:4]}-{mo:02d}-01"
                doc["period_end"] = f"{_ud[:4]}-{mo:02d}-{last_day:02d}"
                doc["period_days"] = last_day
        else:
            doc["period_start"] = _ud or ""
            doc["period_end"] = _ud or ""
            doc["period_days"] = 1
    return doc
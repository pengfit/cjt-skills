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
import re

from gov_price_etl.classify.category_v3 import classify_v3
from gov_price_etl.parse_spec import get_parser
from gov_price_etl.transform.clean import clean_breed, clean_unit, clean_price, clean_spec


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

    # 2026-07-08: 优先用 ODS 拆好的 breed_clean 字段（吉林 v0.2 等已入库前拆）
    # 没有的话 fallback 到 clean_breed(breed_raw)。新疆/菏泽/陕西 ODS 也有
    # breed_clean 字段，其他城市未提供时不影响行为。
    ods_breed_clean = raw.get("breed_clean", "").strip()
    if ods_breed_clean:
        breed_clean = ods_breed_clean
    else:
        breed_clean = clean_breed(breed_raw)
    spec_clean = clean_spec(spec_raw)
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
    category_l3 = v2.get("l3", "")  # v0.7+:v2 L3 编码,透传 parser.parse() 用于白名单过滤

    price = clean_price(raw.get("price")) or 0.0
    tax_price = clean_price(raw.get("tax_price")) or 0.0
    # Crawler bug: when is_tax="0" (不含税), wrote 不含税价 to tax_price, left price=0
    # Fix: if price==0 but tax_price has value, use tax_price as the price
    if price == 0.0 and tax_price > 0:
        price = tax_price
        tax_price = 0.0

    parser = get_parser(city)
    # breed_raw 用于查规则库（规则里存的是原始格式），breed_clean 用于分类/展示
    spec_parsed = parser.parse(spec_clean, breed_raw, category, category_l3)
    if not spec_parsed:
        # 回退：用 clean_breed 再查一次（部分规则可能用 clean 格式录入）
        spec_parsed = parser.parse(spec_clean, breed_clean, category, category_l3)

    # v4 (2026-07-02) : 重庆园林景观类补调专用解析器（合成 spec 格式: 干径X 冠径Y）
    if city == "chongqing" and category == "园林景观":
        try:
            from gov_price_etl.parse_spec.chongqing_landscape import parse_landscape_spec
            landscape_attrs = parse_landscape_spec(spec_clean)
            if landscape_attrs:
                # 合并：园林解析的优先（造有结构的字段名）
                spec_parsed = {**spec_parsed, **landscape_attrs}
        except Exception:
            pass

    # ── v0.7: DWD 不再存 attr(避免脏数据随 DWD→DWS 阶段 1 扩散)──
    # attr 改为 DWS sync 阶段通过 _parse_spec_local 现算,
    # attr_source 永远是 local_db / ai / ai_fallback,不再有 etl 脏数据。
    # spec_parsed 仍解析(用于调试),但不写 DWD 持久化字段。
    spec_parsed = {k: v for k, v in spec_parsed.items() if v}
    nested_attr = []  # 显式空 list,确保 DWD 不带 attr

    doc = {
        "breed": breed_raw,
        "breed_clean": breed_clean,
        "spec": spec_clean,
        "unit": unit_clean,
        "price": price,
        "tax_price": tax_price,
        # v4 (2026-07-02) : 区间价字段透传
        "price_min":   raw.get("price_min") or 0.0,
        "price_max":   raw.get("price_max") or 0.0,
        "price_range": raw.get("price_range") or "",
        "is_range":    raw.get("is_range", False),
        "is_tax":      raw.get("is_tax") or "",
        "range_notes": raw.get("range_notes") or "",
        "spec_notes":  raw.get("spec_notes") or "",
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
        # ── 模糊匹配追溯字段（仅 db_fuzzy_v3 命中时存在，2026-06-30 补充）──
        # fuzzy_match: True 表示分类来源是 stage 2 模糊召回（contain / jaccard）
        # dashboard 可筛 fuzzy_match=true 人工 review；错的回写规则后增量重跑即可
        "fuzzy_match":  v2.get("fuzzy_match", False),
        "fuzzy_method": v2.get("fuzzy_method", ""),
        "fuzzy_score":  v2.get("fuzzy_score", 0.0),
        "province": raw.get("province", ""),
        "city": raw.get("city", ""),
        "county": raw.get("county", ""),
        "tab_type": raw.get("tab_type", ""),
        "tab_name": raw.get("tab_name", ""),
        "update_date": raw.get("update_date", ""),
        "publish_time": raw.get("publish_time", ""),
        "period": raw.get("period", ""),
        "month": raw.get("month", ""),        # 业务期 YYYY-MM（xian --period 模式有）
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

    # 派生 period_start / end / days（如果 ODS 已有则用，否则按 month / period / update_date 派生）
    granularity = doc.get("period_granularity", "monthly")
    _ud = doc.pop("_raw_update_date", "")
    raw_ps = doc.pop("_raw_period_start", "")
    raw_pe = doc.pop("_raw_period_end", "")
    raw_pd = doc.pop("_raw_period_days", "")

    # 优先级：
    #   1) ODS 已有 period_start 字段 → 直接用
    #   2) ODS 有 month 字段（YYYY-MM 字符串）→ period_start = YYYY-MM-01
    #   3) ODS 有 period 字段（YYYY.N期 / YYYY.第N期）→ 按 granularity 派生
    #   4) fallback 到 update_date
    _derived = None  # tuple(period_start, period_end, period_days)
    if raw_ps:
        _derived = (raw_ps, raw_pe or raw_ps, raw_pd or 30)
    else:
        # 优先级 2：month
        _month = doc.get("month", "")
        if _month and re.fullmatch(r"\d{4}-\d{2}", str(_month)):
            y, mo = _month.split("-")
            mo_int = int(mo)
            if granularity == "quarterly":
                q = (mo_int - 1) // 3 + 1
                sm = (q - 1) * 3 + 1
                em = q * 3
                _derived = (f"{y}-{sm:02d}-01", f"{y}-{em:02d}-30", 90)
            else:
                last_day = 31 if mo_int in (1,3,5,7,8,10,12) else (28 if mo_int == 2 else 30)
                _derived = (f"{y}-{int(mo):02d}-01", f"{y}-{int(mo):02d}-{last_day:02d}", last_day)
        # 优先级 3：period 字段解析 YYYY.N期 / YYYY.第N期
        elif doc.get("period"):
            _ps = _parse_period_field(doc["period"], granularity)
            if _ps:
                _derived = _ps
    # 优先级 4：fallback update_date
    if _derived is None and _ud and len(_ud) >= 7:
        try:
            mo = int(_ud[5:7])
        except (ValueError, IndexError):
            mo = 1
        if granularity == "quarterly":
            q = (mo - 1) // 3 + 1
            sm = (q - 1) * 3 + 1
            em = q * 3
            _derived = (f"{_ud[:4]}-{sm:02d}-01", f"{_ud[:4]}-{em:02d}-30", 90)
        else:
            last_day = 31
            if mo == 2:
                last_day = 28
            elif mo in (4, 6, 9, 11):
                last_day = 30
            _derived = (f"{_ud[:4]}-{mo:02d}-01", f"{_ud[:4]}-{mo:02d}-{last_day:02d}", last_day)

    if _derived:
        doc["period_start"], doc["period_end"], doc["period_days"] = _derived
    else:
        doc["period_start"] = _ud or ""
        doc["period_end"] = _ud or ""
        doc["period_days"] = 1
    return doc


def _parse_period_field(period: str, granularity: str):
    """解析 ODS 的 period 字段（如 '2026.1期' / '2026.第1期' / '2026年第3季度'）。
    返回 (period_start, period_end, period_days) 或 None。
    """
    if not period:
        return None
    s = str(period).strip()
    # 模式 1: YYYY.N期  或  YYYY第N期
    m = re.search(r"(\d{4})[.\s]*第?\s*(\d+)\s*期", s)
    if m:
        year, issue = int(m.group(1)), int(m.group(2))
        if granularity == "quarterly":
            # N 当季度：Q1=1-3月, Q2=4-6月, Q3=7-9月, Q4=10-12月
            sm = (issue - 1) * 3 + 1
            em = issue * 3
            return (f"{year}-{sm:02d}-01", f"{year}-{em:02d}-30", 90)
        elif granularity == "bimonthly":
            # 双月刊：N=1→1-2月, N=2→3-4月, ...
            sm = (issue - 1) * 2 + 1
            em = sm + 1
            last_day_e = 31 if em in (1,3,5,7,8,10,12) else (28 if em == 2 else 30)
            return (f"{year}-{sm:02d}-01", f"{year}-{em:02d}-{last_day_e:02d}", 60)
        else:
            # monthly：N 当月份（限 1-12）
            if 1 <= issue <= 12:
                last_day = 31 if issue in (1,3,5,7,8,10,12) else (28 if issue == 2 else 30)
                return (f"{year}-{issue:02d}-01", f"{year}-{issue:02d}-{last_day:02d}", last_day)
    # 模式 2: YYYY-MM  (兜底)
    m = re.search(r"(\d{4})-(\d{2})", s)
    if m:
        year, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            last_day = 31 if mo in (1,3,5,7,8,10,12) else (28 if mo == 2 else 30)
            return (f"{year}-{mo:02d}-01", f"{year}-{mo:02d}-{last_day:02d}", last_day)
    return None

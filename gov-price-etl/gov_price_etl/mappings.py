"""mappings.py - DWD / DWS / ODS 索引 mapping

只放 mapping 定义，不创建模板（templates 由 indexer 创建）。

三层索引的职责：
  ODS — 原始采集层，字段尽量宽（采集器决定怎么写）。
        dynamic=strict 保护：任何未声明字段会被 ES 拒收，
        迫使采集器主动更新 mapping（避免 dynamic 推断造成类型不可控）。
  DWD — 清洗层，分类/价格区间/spec 规范化都在这层完成。
        dynamic=true 允许 transform_doc 写新字段。
  DWS — 服务层，与前端对接，按业务查询需要的字段。
        dynamic=true。

v0.5 (2026-07-02) 新增 build_ods_mapping()：
  - 之前 17 个城市 skill 各自维护一份 ensure_ods_index mapping，重复且不一致
  - 抽出后单点维护，新城市只需声明城市特化字段（city_extension）
"""
# ── ODS mapping（v0.5 新增，2026-07-02）─────────────────────
# 标准 ODS 字段：所有城市共享
# 区间价 v4（2026-07-02 chongqing 抽出的 _parse_interval_price）透传字段
_ODS_BASE_FIELDS = {
    # ── 业务主字段（普适） ─────────────────────────
    "breed":        {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
    "breed_clean":  {"type": "keyword"},
    "spec":         {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
    "unit":         {"type": "keyword"},
    "price":        {"type": "float"},
    "tax_price":    {"type": "float"},
    # ── 区间价 v4 字段（chongqing 抽出后各城市复用） ────────────
    # 2026-07-02 chongqing v3 抽出到 gov_price_etl.parse_price，所有
    # 省平台（jiangxi/sichuan/jinan 等）都有区间价/特殊词场景，
    # ODS mapping 统一声明避免 dynamic 推断造成类型不可控。
    "price_min":    {"type": "float"},   # 区间下界 / "大于200" 的 200
    "price_max":    {"type": "float"},   # 区间上界 / "大于200" 的 200
    "price_range":  {"type": "keyword"}, # 原始区间串（'115-173' / '大于200'）
    "is_range":     {"type": "boolean"}, # 是否区间价（控制聚合时的语义）
    "is_tax":       {"type": "keyword"}, # '0'=不含税 '1'=含税（与重庆一致）
    "range_notes":  {"type": "keyword"}, # 特殊词（'全冠' / '面议' 等）
    "spec_notes":   {"type": "keyword"}, # 补充说明（如园林景观的科属）
    # ── 分类 / 时间 / 位置 ─────────────────────────────
    "category":        {"type": "keyword"},
    "category_l1":     {"type": "keyword"},  # v3 4 层分类 L1（如"建筑工程"）
    "category_l2":     {"type": "keyword"},
    "category_l3":     {"type": "keyword"},
    "period":          {"type": "keyword"},
    "period_start":    {"type": "date", "format": "yyyy-MM-dd"},
    "period_end":      {"type": "date", "format": "yyyy-MM-dd"},
    "period_days":     {"type": "integer"},
    "update_date":     {"type": "date", "format": "yyyy-MM-dd"},
    "publish_time":    {"type": "date", "format": "strict_date_optional_time||epoch_millis", "ignore_malformed": True},
    "create_time":     {"type": "date", "format": "strict_date_optional_time||epoch_millis||yyyy-MM-dd HH:mm:ss", "ignore_malformed": True},
    "province":        {"type": "keyword"},
    "city":            {"type": "keyword"},
    "county":          {"type": "keyword"},
    # ── 周期 / 源站标识 (xian/jinan/sichuan 都用) ──────
    "month":           {"type": "keyword"},  # YYYY-MM 业务期（xian --period 模式）
    "published_at":    {"type": "date", "format": "yyyy-MM-dd"},  # 源站页脚公布日期
    "period_id":       {"type": "keyword"},  # 源站原始周期 ID（jinan --period_id 模式）
    "code":            {"type": "keyword"},  # 源站材料编码（xian/jinan/shaanxi 等）
    # ── 元字段 / 采集侧标识 ─────────────────────────
    "tab_type":        {"type": "keyword"},  # 采集器分类（如 chongqing 'district'/'mortar'/'citywide'）
    "tab_name":        {"type": "keyword"},
    "source":          {"type": "keyword"},  # 业务侧 source（与 tab_type 区别：source 是价格表大类）
    "source_index":    {"type": "keyword"},  # 来源 ODS 索引名
    "run_id":          {"type": "keyword"},  # 本次采集 run 标识
    "area_code":       {"type": "keyword"},  # 行政区划代码（henan/xinjiang 用）
    # ── 数据来源 / 附件溯源 ─────────────────────────
    "source_url":      {"type": "keyword"},
    "source_pdf":      {"type": "keyword"},
    "source_file":     {"type": "keyword"},
    "source_id":       {"type": "keyword"},
    "minio_key":       {"type": "keyword"},
    # ── 备注 / 其他字段 ────────────────────────────
    "no":              {"type": "keyword"},  # 编号（如 hainan 'no'）
    "remark":          {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 1024}}},
    "citywide_category": {"type": "keyword"},  # 城市级材料信息价大类（chongqing citywide tab）
}


def build_ods_mapping(city_extension: dict = None) -> dict:
    """构建 ODS 索引 mapping（标准模板 + 城市特化）。

    Args:
        city_extension: 城市特化字段声明，会与标准字段合并。
                        例如 xinjiang 加 areaid、hainan 加 remark 的子字段。
                        同名字段会被城市特化覆盖。

    Returns:
        ES mapping dict，含 settings 和 mappings.properties。

    动态策略：
        dynamic=strict — 拒绝未声明字段。
        背景：之前 17 个城市 dynamic=true，dynamic 推断的字段一旦写入
        就定型（如某个 spec 字段被推成 text，但业务上需要 keyword 聚合）。
        改 strict 后，采集器写新字段必须先 update mapping，避免运行时类型
        陷阱。

    用法：
        from gov_price_etl.mappings import build_ods_mapping
        mapping = build_ods_mapping()
        # 城市特化示例（xinjiang）：
        mapping = build_ods_mapping(city_extension={
            "areaid": {"type": "integer"},
            "area_name": {"type": "keyword"},
        })
    """
    properties = dict(_ODS_BASE_FIELDS)
    if city_extension:
        properties.update(city_extension)
    return {
        "mappings": {
            "dynamic": "strict",
            "properties": properties,
        },
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    }


# ── DWD mapping ──────────────────────────────────────────────────────────
def build_dwd_mapping() -> dict:
    base = {
        # ── 基础字段（2026-06-17 合并：v1/v2 共用字段统一名称）──
        "breed":           {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
        "breed_clean":     {"type": "keyword"},
        "spec":            {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
        "unit":            {"type": "keyword"},
        "price":           {"type": "float"},
        "tax_price":       {"type": "float"},
        "category":        {"type": "keyword"},         # v2 L1 中文名（如"建筑工程"）—— spec 规则库按此过滤
        "province":        {"type": "keyword"},
        "city":            {"type": "keyword"},
        "county":          {"type": "keyword"},
        "tab_type":        {"type": "keyword"},
        "tab_name":        {"type": "keyword"},
        "update_date":     {"type": "keyword"},
        "publish_time":    {"type": "date", "format": "strict_date_optional_time||epoch_millis", "ignore_malformed": True},
        "period":          {"type": "text"},
        "code":            {"type": "keyword"},
        "source_index":    {"type": "keyword"},
        "etl_time":        {"type": "date", "format": "strict_date_optional_time||epoch_millis", "ignore_malformed": True},
        # ── 时序字段（2026-06-24 ES 实测 DWD 索引里有这些 dynamic 推断的脏字段，补上声明以对齐）──
        "period_start":    {"type": "date", "format": "strict_date_optional_time||epoch_millis", "ignore_malformed": True},  # 期间起始日
        "period_end":      {"type": "date", "format": "strict_date_optional_time||epoch_millis", "ignore_malformed": True},  # 期间结束日
        "period_days":     {"type": "integer"},  # 期间天数
        "attr": {
            "type": "nested",
            "properties": {"k": {"type": "keyword"}, "v": {"type": "keyword"}},
        },

        # ── v2 4 层分类字段（2026-06-16 阶段 2 接入）──
        # 4 层分类
        "category_l1":     {"type": "keyword"},         # 8 L1 专业大类
        "category_l2":     {"type": "keyword"},         # 31 L2 分部工程
        "category_l3":     {"type": "keyword"},         # 50 L3 分项工程
        "category_l4":     {"type": "keyword"},         # L4 细目（500+，MVP 暂用 UNCLASSIFIED）
        "category_name_l1": {"type": "keyword"},        # L1 中文名（如"建筑工程"）—— 2026-06-16 加，前缀统一 category_
        "category_name_l2": {"type": "keyword"},        # L2 中文名（如"钢结构工程"）
        "category_name_l3": {"type": "keyword"},        # L3 中文名（如"钢构件"）
        # 工程属性
        "eng_part":        {"type": "keyword"},         # 基础/主体/装饰/安装/...
        "eng_stage":       {"type": "keyword"},         # 设计/施工/运维（多选拼接："设计,施工"）
        "main_or_aux":     {"type": "keyword"},         # 主材/辅材
        # 标准码（跨国/跨系统对接用）
        "gb_50500":        {"type": "keyword"},         # GB 50500 清单项目编码（6 位）
        "quota_ref":       {"type": "keyword"},         # 消耗量定额参考号（如 "5-31"）
        "ifc_class":       {"type": "keyword"},         # IFC 4.3 类名（IfcColumn / IfcPipeSegment / ...）
        "uniclass_ss":     {"type": "keyword"},         # Uniclass 2015 Ss_/Pr_ 编码
        # 物料视图主键
        "material_code":   {"type": "keyword"},         # 跨城市一致的物料编码（v2 字典生成）
        # v2 分类元信息
        "category_v2_source":      {"type": "keyword"},  # db_exact_v2 / db_fuzzy_v2 / pattern_v2 / ai_v2 / fallback_v2
        "category_v2_confidence":  {"type": "float"},    # 0-1 置信度
    }
    return {
        "mappings": {"properties": base, "dynamic": True},
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    }


# ── DWS mapping ──────────────────────────────────────────────────────────
def build_dws_mapping() -> dict:
    base = {
        "spec":              {"type": "text"},
        "breed":             {"type": "keyword"},
        "breed_clean":       {"type": "keyword"},
        "category":          {"type": "keyword"},
        "category_l1":       {"type": "keyword"},
        "category_l2":       {"type": "keyword"},
        "category_l3":       {"type": "keyword"},
        "category_l4":       {"type": "keyword"},
        "category_name_l1":  {"type": "keyword"},
        "category_name_l2":  {"type": "keyword"},
        "category_name_l3":  {"type": "keyword"},
        "category_v2_source":      {"type": "keyword"},
        "category_v2_confidence":  {"type": "float"},
        "unit":              {"type": "keyword"},
        "price":             {"type": "float"},
        "tax_price":         {"type": "float"},
        "region":            {"type": "keyword"},
        "county":            {"type": "keyword"},
        "city":              {"type": "keyword"},
        "province":          {"type": "keyword"},
        "date":              {"type": "date", "format": "strict_date_optional_time||epoch_millis", "ignore_malformed": True},
        "update_date":       {"type": "keyword"},
        "etl_time":          {"type": "date", "format": "strict_date_optional_time||epoch_millis", "ignore_malformed": True},
        "create_time":       {"type": "date", "format": "strict_date_optional_time||epoch_millis", "ignore_malformed": True},
        "publish_time":      {"type": "date", "format": "strict_date_optional_time||epoch_millis", "ignore_malformed": True},
        # ── 时序分析专用字段（2026-06-23 补充，跨周期时序查询需要）──
        "source_publish_date": {"type": "date", "format": "strict_date_optional_time||epoch_millis", "ignore_malformed": True},  # 源站实际发布日期
        "period_granularity":  {"type": "keyword"},  # monthly / quarterly / bimonthly / half_yearly / irregular
        "period_start":        {"type": "date", "format": "strict_date_optional_time||epoch_millis", "ignore_malformed": True},  # 期间起始日
        "period_end":          {"type": "date", "format": "strict_date_optional_time||epoch_millis", "ignore_malformed": True},  # 期间结束日
        "period_days":         {"type": "integer"},  # 期间天数（yearly_normalized 折算用）
        "period_id":           {"type": "keyword"},  # 源站原始期间名（如 '2026.5月' / '2026.1-3月' / '2026-04-01'）
        "code":              {"type": "keyword"},
        "tab_type":          {"type": "keyword"},
        "tab_name":          {"type": "keyword"},
        "period":            {"type": "text"},
        "source":            {"type": "keyword"},
        "citywide_category": {"type": "keyword"},
        "source_index":      {"type": "keyword"},
        "attr": {
            "type": "nested",
            "properties": {"k": {"type": "keyword"}, "v": {"type": "keyword"}},
        },
    }
    return {
        "mappings": {"properties": base},
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
    }

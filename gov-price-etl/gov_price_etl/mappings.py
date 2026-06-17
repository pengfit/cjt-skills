"""mappings.py - DWD / DWS 索引 mapping

只放 mapping 定义，不创建模板（templates 由 indexer 创建）。
"""
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

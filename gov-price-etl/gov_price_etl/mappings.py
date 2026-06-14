"""mappings.py - DWD / DWS 索引 mapping

只放 mapping 定义，不创建模板（templates 由 indexer 创建）。
"""
# ── DWD mapping ──────────────────────────────────────────────────────────
def build_dwd_mapping() -> dict:
    base = {
        "breed":           {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
        "breed_clean":     {"type": "keyword"},
        "spec":            {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
        "unit":            {"type": "keyword"},
        "price":           {"type": "float"},
        "tax_price":       {"type": "float"},
        "category":        {"type": "keyword"},
        "category_system": {"type": "keyword"},
        "category_system_name": {"type": "keyword"},
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
        "category_system":   {"type": "keyword"},
        "category_system_name": {"type": "keyword"},
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

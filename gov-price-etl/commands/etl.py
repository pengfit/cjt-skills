#!/usr/bin/env python3
"""etl.py - gov-price ETL 主程序

从 5 个 ods_* 索引读取原始数据，清洗品种/规格/单位，
计算分类，写入 dwd_{city}_price。

用法:
    python3 etl.py                    # 全量（所有城市）
    python3 etl.py --city sichuan     # 只处理指定城市
    python3 etl.py --incremental      # 增量（根据 update_date）
    python3 etl.py --dry-run          # 预览（前100条）
"""

import argparse
import json
import time
import sys
import os
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

try:
    import requests
    import yaml
except ImportError:
    print("请安装依赖: pip3 install requests pyyaml")
    sys.exit(1)

from classify import classify_breed, _fetch_ai_category_batch
from parse_spec import parse_spec, get_parser
from parse_spec.base import clean_spec
from clean import clean_breed, clean_unit, clean_price

# ─── category → category_system 映射 ────────────────────────────────────────
_CATEGORY_SYSTEM_MAP: dict[str, str] = {}

def _load_category_system_map() -> dict[str, str]:
    """从 category_in_system.json 构建 category name → code 映射。"""
    rules_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(rules_dir, "classify", "rules", "category_in_system.json")
    m = {}
    if os.path.exists(json_path):
        with open(json_path) as f:
            data = json.load(f)
        for group in data.get("categories", []):
            for child in group.get("children", []):
                m[child["name"]] = child["code"]
    return m

def _get_category_system_map() -> dict[str, str]:
    global _CATEGORY_SYSTEM_MAP
    if not _CATEGORY_SYSTEM_MAP:
        _CATEGORY_SYSTEM_MAP = _load_category_system_map()
    return _CATEGORY_SYSTEM_MAP

# ─── AI 分类结果缓存（进程内，同一 breed 不重复调用 AI）───────────────────────
def load_config():
    cfg_path = os.path.join(os.path.dirname(SCRIPT_DIR), "config.yml")
    with open(cfg_path) as f:
        return yaml.safe_load(f)


def get_es_client(host: str):
    return requests.Session()


# ─── 城市配置 ────────────────────────────────────────────────────────────────
CITY_CONFIGS = {
    "xian": {
        "ods": "ods_material_xian_price",
        "dwd": "dwd_xian_price",
        "dws": "dws_xian_price",
        "city_label": "西安",
    },
    "sichuan": {
        "ods": "ods_material_sichuan_price",
        "dwd": "dwd_sichuan_price",
        "dws": "dws_sichuan_price",
        "city_label": "四川",
    },
    "chongqing": {
        "ods": "ods_material_chongqing_price",
        "dwd": "dwd_chongqing_price",
        "dws": "dws_chongqing_price",
        "city_label": "重庆",
    },
    "jinan": {
        "ods": "ods_material_jinan_price",
        "dwd": "dwd_jinan_price",
        "dws": "dws_jinan_price",
        "city_label": "济南",
    },
    "rizhao": {
        "ods": "ods_material_rizhao_price",
        "dwd": "dwd_rizhao_price",
        "dws": "dws_rizhao_price",
        "city_label": "日照",
    },
}

DWD_MAPPING = {
    "mappings": {
        "properties": {
            "breed": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "breed_clean": {"type": "keyword"},
            "spec": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "unit": {"type": "keyword"},
            "thickness": {"type": "keyword"},
            "length": {"type": "keyword"},
            "width": {"type": "keyword"},
            "height": {"type": "keyword"},
            "height_range": {"type": "keyword"},
            "diameter": {"type": "keyword"},
            "ring_stiffness": {"type": "keyword"},
            "pressure": {"type": "keyword"},
            "material": {"type": "keyword"},
            "color": {"type": "keyword"},
            "grade": {"type": "keyword"},
            "voltage": {"type": "keyword"},
            "current": {"type": "keyword"},
            "cross_section": {"type": "keyword"},
            "asphalt_type": {"type": "keyword"},
            "cement_content": {"type": "keyword"},
            "channels": {"type": "keyword"},
            "doors": {"type": "keyword"},
            "cores": {"type": "keyword"},
            "fiber_core": {"type": "keyword"},
            "length_range": {"type": "keyword"},
            "media": {"type": "keyword"},
            "range": {"type": "keyword"},
            "output": {"type": "keyword"},
            "cable_length": {"type": "keyword"},
            "temp_range": {"type": "keyword"},
            "humidity_range": {"type": "keyword"},
            "surface": {"type": "keyword"},
            "series": {"type": "keyword"},
            "fire_rating": {"type": "keyword"},
            "temperature": {"type": "keyword"},
            "installation_type": {"type": "keyword"},
            "installation_type": {"type": "keyword"},
            "drain_type": {"type": "keyword"},
            "inlet_type": {"type": "keyword"},
            "form": {"type": "keyword"},
            "ip_rating": {"type": "keyword"},
            "needs_spec_parse": {"type": "boolean"},
            "inner_diameter": {"type": "keyword"},
            "wall_thickness": {"type": "keyword"},
            "price": {"type": "float"},
            "tax_price": {"type": "float"},
            "category": {"type": "keyword"},
            "category_system": {"type": "keyword"},
            "province": {"type": "keyword"},
            "city": {"type": "keyword"},
            "county": {"type": "keyword"},
            "tab_type": {"type": "keyword"},
            "tab_name": {"type": "keyword"},
            "update_date": {"type": "date"},
            "publish_time": {"type": "date", "format": "strict_date_optional_time||epoch_millis", "ignore_malformed": True},
            "period": {"type": "text"},
            "code": {"type": "keyword"},
            "source_index": {"type": "keyword"},
            "etl_time": {"type": "date", "format": "strict_date_optional_time||epoch_millis", "ignore_malformed": True},
        }
    },
    "settings": {"number_of_shards": 1, "number_of_replicas": 0}
}


# ─── 单条转换 ────────────────────────────────────────────────────────────────
def transform_doc(raw: dict, source_index: str, city: str) -> dict:
    """将一条 ODS 原始文档清洗为 DWD 格式"""
    breed_raw = raw.get("breed", "")
    spec_raw = raw.get("spec", "")
    unit_raw = raw.get("unit", "")

    breed_clean = clean_breed(breed_raw)
    spec_clean = spec_raw
    unit_clean = clean_unit(unit_raw)
    category = classify_breed(breed_clean, spec_clean)

    price = clean_price(raw.get("price"))
    tax_price = clean_price(raw.get("tax_price"))

    parser = get_parser(city)
    spec_parsed = parser.parse(spec_clean, breed_clean, category)

    if not spec_clean or spec_clean == "/":
        needs_spec_parse = False
    else:
        attr_keys = [k for k, v in spec_parsed.items() if v]
        needs_spec_parse = len(attr_keys) == 0

    def gp(key, default=""):
        v = spec_parsed.get(key)
        return v if v else default

    # 动态字段：所有 spec 属性（_ATTR_NESTED 兜底），仅保留非空值
    # spec_parsed 中可能有 parser 返回的新字段（不在 _ATTR_NESTED 中），全部纳入
    spec_dynamic = {k: v for k, v in spec_parsed.items() if v}
    static_attrs = {f: gp(f) for f in _ATTR_NESTED if gp(f)}
    attr = {**static_attrs, **spec_dynamic}

    return {
        "breed": breed_raw,
        "breed_clean": breed_clean,
        "spec": spec_clean,
        "needs_spec_parse": needs_spec_parse,
        "unit": unit_clean,
        "price": price,
        "tax_price": tax_price,
        "category": category,
        "category_system": _get_category_system_map().get(category, ""),
        "province": raw.get("province", ""),
        "city": raw.get("city", ""),
        "county": raw.get("county", ""),
        "tab_type": raw.get("tab_type", ""),
        "tab_name": raw.get("tab_name", ""),
        "update_date": raw.get("update_date", ""),
        "publish_time": raw.get("publish_time", ""),
        "period": raw.get("period", ""),
        "code": raw.get("code", ""),
        "source_index": source_index,
        "etl_time": datetime.now().isoformat(),
        **attr,
    }


def ensure_indices(es_host: str, cfg: dict):
    """统一入口：确保 dwd/dws 索引存在，新建时自动套用 index template。"""
    _setup_index_templates(es_host)
    dwd_idx, dws_idx = cfg["dwd"], cfg["dws"]
    s = get_es_client(es_host)
    for idx in (dwd_idx, dws_idx):
        r = s.head(f"{es_host}/{idx}")
        if r.status_code == 404:
            print(f"  [idx] 创建索引 {idx} ...")
            s.put(f"{es_host}/{idx}", json={})  # template 自动套用
            print(f"  [idx] {idx} 创建完成（套用 template）")


def _setup_index_templates(es_host: str):
    """幂等创建/更新 gov_dwd / gov_dws 两个 index template。"""
    for name, pattern, mapping in [
        ("gov_dwd", "dwd_*", _build_dwd_mapping()),
        ("gov_dws", "dws_*", _build_dws_mapping()),
    ]:
        r = get_es_client(es_host).put(f"{es_host}/_index_template/{name}", json={
            "index_patterns": [pattern],
            "template": {"settings": mapping["settings"], "mappings": mapping["mappings"]},
            "priority": 100,
        })
        tag = "OK" if r.status_code in (200, 201) else f"FAIL {r.status_code}"
        print(f"  [template] {name} → {pattern} {tag}")


def _build_dwd_mapping():
    base = {
        "breed":         {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
        "breed_clean":   {"type": "keyword"},
        "spec":          {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
        "unit":          {"type": "keyword"},
        "price":         {"type": "float"},
        "tax_price":     {"type": "float"},
        "category":      {"type": "keyword"},
        "category_system": {"type": "keyword"},
        "province":      {"type": "keyword"},
        "city":          {"type": "keyword"},
        "county":        {"type": "keyword"},
        "tab_type":      {"type": "keyword"},
        "tab_name":      {"type": "keyword"},
        "update_date":   {"type": "keyword"},
        "publish_time":  {"type": "date", "format": "strict_date_optional_time||epoch_millis", "ignore_malformed": True},
        "period":        {"type": "text"},
        "code":          {"type": "keyword"},
        "source_index":  {"type": "keyword"},
        "etl_time":      {"type": "date", "format": "strict_date_optional_time||epoch_millis", "ignore_malformed": True},
        "needs_spec_parse": {"type": "boolean"},
    }
    for f in [
        "length","width","thickness","height","diameter","ring_stiffness","pressure",
        "material","color","grade","voltage","current","cross_section",
        "asphalt_type","cement_content","channels","doors","cores","fiber_core",
        "length_range","height_range","media","range","output","cable_length",
        "temp_range","humidity_range","surface","series","fire_rating",
        "temperature","installation_type","drain_type","inlet_type",
        "form","ip_rating","inner_diameter","wall_thickness",
    ]:
        base[f] = {"type": "keyword"}
    return {"mappings": {"properties": base}, "settings": {"number_of_shards": 1, "number_of_replicas": 0}}


_ATTR_NESTED = [
    "diameter","thickness","length","width","height",
    "material","grade","pressure","cores","voltage","current",
    "form","color","series","temperature",
    "temp_range","humidity_range","length_range","height_range",
    "inner_diameter","wall_thickness","fiber_core","cable_length",
    "channels","doors","media","range","output",
    "ip_rating","fire_rating","ring_stiffness",
    "cross_section","drain_type","inlet_type","installation_type",
    "asphalt_type","cement_content","surface",
]


def _build_dws_mapping():
    base = {
        "spec":              {"type": "text"},
        "breed":             {"type": "keyword"},
        "breed_clean":       {"type": "keyword"},
        "category":          {"type": "keyword"},
        "category_system":   {"type": "keyword"},
        "unit":              {"type": "keyword"},
        "price":             {"type": "float"},
        "tax_price":         {"type": "float"},
        "region":            {"type": "keyword"},
        "county":            {"type": "keyword"},
        "city":              {"type": "keyword"},
        "province":          {"type": "keyword"},
        "date":              {"type": "date"},
        "update_date":       {"type": "keyword"},
        "etl_time":          {"type": "date"},
        "publish_time":      {"type": "date"},
        "needs_spec_parse":  {"type": "boolean"},
        "code":              {"type": "keyword"},
        "tab_type":          {"type": "keyword"},
        "tab_name":          {"type": "keyword"},
        "period":            {"type": "text"},
        "source_index":      {"type": "keyword"},
        "attr": {
            "type": "nested",
            "dynamic": True,
            "properties": {"k": {"type": "keyword"}, "v": {"type": "keyword"}},
        },
    }
    return {"mappings": {"properties": base}, "settings": {"number_of_shards": 1, "number_of_replicas": 0}}


# ── backward compat stubs (keep signatures so existing callers don't break) ──
def ensure_dwd(es_host: str, dwd_index: str):
    pass  # now handled by ensure_indices


def ensure_dws(es_host: str, dws_index: str):
    pass  # now handled by ensure_indices

def bulk_index(es_host: str, index: str, docs: list, ids: list = None, mark_done: bool = False) -> tuple:
    if not docs:
        return 0, 0
    if mark_done:
        for doc in docs:
            doc["needs_spec_parse"] = False
    session = get_es_client(es_host)
    body = ""
    for i, doc in enumerate(docs):
        # 优先用 ids 里的 _id（来自 ODS 的真实 _id），确保 ai_pending 更新时能命中
        _id = ids[i] if (ids and i < len(ids) and ids[i]) else None
        action = {"index": {"_id": _id}} if _id else {"index": {}}
        body += json.dumps(action, ensure_ascii=False) + "\n"
        body += json.dumps(doc, ensure_ascii=False) + "\n"

    resp = session.post(f"{es_host}/{index}/_bulk", data=body.encode("utf-8"),
                        headers={"Content-Type": "application/x-ndjson"})
    result = resp.json()
    errors = sum(1 for item in result.get("items", []) if "error" in item.get("index", {}))
    ok = len(docs) - errors
    return ok, errors


# ─── DWD → DWS 同步 ──────────────────────────────────────────────────────────
# DWS 的 attr 字段是 nested object，从 DWD 的扁平字段构建
ATTR_FIELDS = (
    "diameter,thickness,length,width,height,material,grade,pressure,ring_stiffness,"
    "cores,voltage,current,cross_section,drain_type,inlet_type,installation_type,"
    "form,ip_rating,color,series,temperature,temp_range,humidity_range,"
    "length_range,height_range,inner_diameter,wall_thickness,fiber_core,"
    "cable_length,channels,doors,media,range,output"
).split(",")


def _build_attr(doc: dict) -> dict:
    """从 DWD 扁平文档中提取 attr nested 字段（仅保留非空值）"""
    attr = {}
    for f in ATTR_FIELDS:
        v = doc.get(f)
        if v and str(v).strip():
            attr[f] = str(v).strip()
    return attr


def flush_to_dws(es_host: str, city: str, cfg: dict, batch_size: int = 500, category: str = "") -> tuple:
    """
    同步 DWD → DWS。

    入池条件（需同时满足）：
      1. needs_spec_parse = False
      2. 至少有一个细分字段（ATTR_FIELDS）非空

    category 不为空时只同步该分类。

    返回 (成功数, 失败数)。
    """
    dwd_idx = cfg["dwd"]
    dws_idx = cfg["dws"]
    session = get_es_client(es_host)

    # 入池：needs_spec_parse=False 且 至少一个细分字段非空（排除空字符串）
    attr_should_clauses = []
    for f in ATTR_FIELDS:
        attr_should_clauses.append(
            {
                "bool": {
                    "must": [
                        {"exists": {"field": f}},
                        {"bool": {"must_not": [{"term": {f: ""}}]}},
                    ]
                }
            }
        )

    body = {
        "query": {
            "bool": {
                "must": [
                    {"term": {"needs_spec_parse": False}},
                    {"bool": {"should": attr_should_clauses, "minimum_should_match": 1}},
                ] + ([{"term": {"category": category}}] if category else [])
            }
        },
        "size": batch_size,
        "sort": [{"update_date": "asc"}],
    }

    resp = session.post(f"{es_host}/{dwd_idx}/_search?scroll=2m", json=body)
    if resp.status_code != 200:
        print(f"  [DWS] 查询 DWD 失败: {resp.text[:200]}")
        return 0, 0

    data = resp.json()
    hits = data["hits"]["hits"]
    scroll_id = data.get("_scroll_id", "")
    total = data["hits"]["total"]
    if isinstance(total, dict):
        total = total.get("value", 0)

    if total == 0:
        print(f"  [DWS] {city}: 无待同步数据")
        return 0, 0

    ensure_indices(es_host, cfg)
    print(f"  [DWS] {city}: {dwd_idx} → {dws_idx} ({total:,} 条待同步)")

    synced = 0
    failed = 0
    pages = 0

    while hits:
        pages += 1
        docs, doc_ids = [], []
        for h in hits:
            d = dict(h["_source"])
            # 构建 DWS 的 attr nested（从 DWD 扁平字段提取）
            d["attr"] = _build_attr(d)
            # 过滤空 date 字段（空字符串无法解析为 date 类型）
            for f in ("date", "publish_time"):
                if not d.get(f):
                    d.pop(f, None)
            # DWD _id 即 ODS _id，复用于 DWS
            docs.append(d)
            doc_ids.append(h["_id"])

        ok, err = bulk_index(es_host, dws_idx, docs, doc_ids)
        synced += ok
        failed += err

        if pages % 20 == 0:
            print(f"    pages={pages}, synced={synced}/{total}")

        resp = session.post(f"{es_host}/_search/scroll?scroll=2m",
                             json={"scroll_id": scroll_id})
        if resp.status_code != 200:
            break
        result = resp.json()
        hits = result["hits"]["hits"]
        scroll_id = result.get("_scroll_id", "")

    if scroll_id:
        session.delete(f"{es_host}/_search/scroll", json={"scroll_id": scroll_id})

    print(f"  [DWS] {city} 完成: synced={synced}, failed={failed}")
    return synced, failed


# ─── 单城市 ETL ────────────────────────────────────────────────────────────────
def etl_city(es_host: str, city: str, cfg: dict,
             batch_size: int = 500, incremental: bool = False,
             since_date: str = "", dry_run: bool = False,
             category: str = "", mark_done: bool = False) -> tuple:
    ods_idx = cfg["ods"]
    dwd_idx = cfg["dwd"]

    ensure_indices(es_host, cfg)

    session = get_es_client(es_host)
    count_resp = session.get(f"{es_host}/{ods_idx}/_count")
    if count_resp.status_code != 200:
        print(f"  [ETL] {city}: 索引 {ods_idx} 不存在或查询失败，跳过")
        return 0, 0

    total = count_resp.json()["count"]
    if total == 0:
        print(f"  [ETL] {city}: {ods_idx} 为空，跳过")
        return 0, 0

    print(f"  [ETL] {city}: {ods_idx} ({total:,} 条) → {dwd_idx}")

    body = {
        "query": {"bool": {"must": [{"match_all": {}}], "must_not": [{"terms": {"spec": ["/", ""]}}]}},
        "size": min(batch_size, total),
        "sort": [{"update_date": "asc"}],
    }

    if category and not (incremental and since_date):
        body["query"] = {"bool": {"must": [{"term": {"category": category}}], "must_not": [{"terms": {"spec": ["/", ""]}}]}}

    if incremental and since_date:
        if category:
            body["query"] = {"bool": {"must": [{"term": {"category": category}}], "must_not": [{"terms": {"spec": ["/", ""]}}]}}
        else:
            body["query"] = {"bool": {"must": [{"range": {"update_date": {"gte": since_date}}}], "must_not": [{"terms": {"spec": ["/", ""]}}]}}

    resp = session.post(f"{es_host}/{ods_idx}/_search?scroll=2m", json=body)
    if resp.status_code != 200:
        print(f"  [ETL] {city}: 查询失败: {resp.text[:200]}")
        return 0, 0

    data = resp.json()
    hits = data["hits"]["hits"]
    scroll_id = data.get("_scroll_id", "")

    etled = 0
    failed = 0
    pages = 0
    # 收集需要 AI 分类的 (breed_clean, doc_id)
    ai_pending: list[tuple[str, str]] = []

    while hits:
        pages += 1
        docs = []
        doc_ids = []

        for h in hits:
            try:
                doc = transform_doc(h["_source"], ods_idx, city)
                spec_val = doc.get("spec", "")
                if not spec_val or spec_val == "/":
                    continue
                if dry_run:
                    print(f"    [dry-run] {doc['breed_clean']} → {doc['category']}")
                    continue
                # category == "其他" 时先写入 DWD（category="其他"），AI 批量分类后再更新
                if doc["category"] == "其他":
                    ai_pending.append((doc["breed_clean"], h["_id"]))
                    # AI 待分类品种：先写入 DWD（不带 category，等 AI 更新时用 update doc_as_upsert 合并）
                    # 注意：初始写入只有基础字段，AI 更新时会补充完整文档
                    ai_doc = {k: v for k, v in doc.items() if k != "category"}
                    docs.append(ai_doc)
                    doc_ids.append(h["_id"])
                    continue
                docs.append(doc)
                doc_ids.append(h["_id"])
            except Exception as e:
                failed += 1
                if failed <= 3:
                    print(f"    转换失败: {e}")

        if docs and not dry_run:
            ok, fail = bulk_index(es_host, dwd_idx, docs, doc_ids, mark_done=mark_done)
            etled += ok
            failed += fail

        if pages % 20 == 0:
            print(f"    pages={pages}, etled={etled}/{total}")

        resp = session.post(f"{es_host}/_search/scroll?scroll=2m",
                             json={"scroll_id": scroll_id})
        if resp.status_code != 200:
            break
        result = resp.json()
        hits = result["hits"]["hits"]
        scroll_id = result.get("_scroll_id", "")

    if scroll_id:
        session.delete(f"{es_host}/_search/scroll", json={"scroll_id": scroll_id})

    # ── 批量 AI 分类 ──
    ai_updated = 0
    if ai_pending and not dry_run:
        breeds = list(dict.fromkeys(b for b, _ in ai_pending))  # 去重保留顺序
        breed_cats: dict = {}
        # 分批调用，每批最多 20 条
        _AI_BATCH_SIZE = 20
        for i in range(0, len(breeds), _AI_BATCH_SIZE):
            chunk = breeds[i:i + _AI_BATCH_SIZE]
            cats = _fetch_ai_category_batch(chunk, city)
            breed_cats.update(cats)
            if i + _AI_BATCH_SIZE < len(breeds):
                import time; time.sleep(10)
        if breed_cats:
            # 按 doc_id 分组批量更新
            update_body = ""
            for breed_clean, doc_id in ai_pending:
                cat = breed_cats.get(breed_clean, "其他")
                # 用 update + doc_as_upsert 代替 index：
                # 文档不存在时自动创建（upsert），存在时只更新 category 字段（不覆盖其他字段）
                update_body += json.dumps({"update": {"_id": doc_id}}, ensure_ascii=False) + "\n"
                update_body += json.dumps({"doc": {"category": cat, "category_system": _get_category_system_map().get(cat, "")}, "doc_as_upsert": True}, ensure_ascii=False) + "\n"
            if update_body:
                _session = get_es_client(es_host)
                r = _session.post(f"{es_host}/{dwd_idx}/_bulk",
                                  data=update_body.encode("utf-8"),
                                  headers={"Content-Type": "application/x-ndjson"})
                result = r.json()
                errors = sum(1 for it in result.get("items", []) if "error" in it.get("update", {}))
                ai_updated = len(ai_pending) - errors
                print(f"  [AI] 批量更新详情: 更新 {ai_updated}/{len(ai_pending)} 条，错误 {errors}")
                if errors > 0:
                    for it in result.get("items", [])[:3]:
                        if "error" in it.get("update", {}):
                            print(f"    错误: {it['update']['error']}")
        print(f"  [AI] 批量分类 {len(ai_pending)} 条 → 更新 {ai_updated} 条")

    print(f"  [ETL] {city} 完成: → {dwd_idx} | etled={etled}, failed={failed}")
    return etled, failed


# ─── 主 ETL ───────────────────────────────────────────────────────────────────
def run_etl(es_host: str, cities: list, batch_size: int = 500,
            incremental: bool = False, since_date: str = "",
            dry_run: bool = False, category: str = "",
            mark_done: bool = False):
    total_etled = 0
    total_failed = 0

    for city in cities:
        if city not in CITY_CONFIGS:
            print(f"[ETL] 未知城市: {city}，跳过")
            continue

        cfg = CITY_CONFIGS[city]
        print(f"\n[ETL] 处理城市: {city} ({cfg['city_label']})")

        ok, fail = etl_city(
            es_host, city, cfg,
            batch_size=batch_size,
            incremental=incremental,
            since_date=since_date,
            dry_run=dry_run,
            category=category,
            mark_done=mark_done,
        )
        total_etled += ok
        total_failed += fail

        dws_ok, dws_fail = flush_to_dws(es_host, city, cfg, batch_size=batch_size)
        print(f"  [DWS] {city} 同步结果: ok={dws_ok}, fail={dws_fail}")

    print(f"\n[ETL] 全部完成: etled={total_etled}, failed={total_failed}")
    return total_etled, total_failed


# ─── CLI ────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="gov-price ETL（多城市）")
    parser.add_argument("--city", default="", help=f"指定城市（空=全部）可用: {', '.join(CITY_CONFIGS.keys())}")
    parser.add_argument("--incremental", action="store_true", help="增量模式")
    parser.add_argument("--dry-run", action="store_true", help="预览模式（不写入）")
    parser.add_argument("--since", default="", help="增量起始日期 YYYY-MM-DD")
    parser.add_argument("--category", default="", help="只清洗指定分类（category 字段过滤）")
    parser.add_argument("--mark-done", action="store_true", help="清洗指定分类时：规则已全部确认，直接标记 needs_spec_parse=False")
    parser.add_argument("--batch-size", type=int, default=500, help="批量大小")
    args = parser.parse_args()

    cfg = load_config()
    es_host = cfg["es"]["host"]

    if args.city:
        cities = [args.city] if args.city in CITY_CONFIGS else []
        if not cities:
            print(f"[ETL] 未知城市: {args.city}")
            print(f"可用城市: {', '.join(CITY_CONFIGS.keys())}")
            sys.exit(1)
    else:
        cities = list(CITY_CONFIGS.keys())

    print(f"[ETL] ES: {es_host}")
    print(f"[ETL] 城市: {', '.join(cities)}")
    print(f"[ETL] 模式: {'增量' if args.incremental else '全量'} {'(dry-run)' if args.dry_run else ''}")

    start = time.time()
    ok, fail = run_etl(
        es_host, cities,
        batch_size=args.batch_size,
        incremental=args.incremental,
        since_date=args.since,
        dry_run=args.dry_run,
        mark_done=args.mark_done,
    )
    print(f"[ETL] 耗时 {time.time()-start:.1f}s | ok={ok}, fail={fail}")


if __name__ == "__main__":
    main()
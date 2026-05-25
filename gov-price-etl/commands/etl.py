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

from classify import classify_breed, get_all_categories, CAT_ID_MAP
from parse_spec import parse_spec, get_parser
from parse_spec.base import clean_spec
from clean import clean_breed, clean_unit, clean_price

# ─── AI 分类结果缓存（进程内，同一 breed 不重复调用 AI）───────────────────────
_AI_CATEGORY_CACHE: dict = {}  # breed_clean → category


def _fetch_ai_category(breed_clean: str, city: str) -> str:
    """查询 AI 补充分类（带缓存，同一 breed 只查一次）"""
    if breed_clean in _AI_CATEGORY_CACHE:
        return _AI_CATEGORY_CACHE[breed_clean]
    import http.client, json as _json
    try:
        body = _json.dumps({"breed": breed_clean, "city": city}).encode("utf-8")
        c = http.client.HTTPConnection("localhost", 5200, timeout=15)
        c.request("POST", "/api/stats/spec-quality/classify-breed", body=body,
                  headers={"Content-Type": "application/json"})
        resp = c.getresponse()
        data = _json.loads(resp.read())
        cat = data.get("category", "其他") if data.get("ok") else "其他"
    except Exception:
        cat = "其他"
    _AI_CATEGORY_CACHE[breed_clean] = cat
    return cat


# ─── 配置 ───────────────────────────────────────────────────────────────────────
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

    if category == "其他":
        category = _fetch_ai_category(breed_clean, city)

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

    return {
        "breed": breed_raw,
        "breed_clean": breed_clean,
        "spec": spec_clean,
        "thickness": gp("thickness"),
        "length": gp("length"),
        "width": gp("width"),
        "height": gp("height"),
        "diameter": gp("diameter"),
        "ring_stiffness": gp("ring_stiffness"),
        "pressure": gp("pressure"),
        "material": gp("material"),
        "color": gp("color"),
        "grade": gp("grade"),
        "voltage": gp("voltage"),
        "current": gp("current"),
        "cross_section": gp("cross_section"),
        "asphalt_type": gp("asphalt_type"),
        "cement_content": gp("cement_content"),
        "channels": gp("channels"),
        "doors": gp("doors"),
        "cores": gp("cores"),
        "fiber_core": gp("fiber_core"),
        "length_range": gp("length_range"),
        "height_range": gp("height_range"),
        "media": gp("media"),
        "range": gp("range"),
        "output": gp("output"),
        "cable_length": gp("cable_length"),
        "temp_range": gp("temp_range"),
        "humidity_range": gp("humidity_range"),
        "surface": gp("surface"),
        "series": gp("series"),
        "fire_rating": gp("fire_rating"),
        "temperature": gp("temperature"),
        "installation_type": gp("installation_type"),
        "drain_type": gp("drain_type"),
        "inlet_type": gp("inlet_type"),
        "form": gp("form"),
        "ip_rating": gp("ip_rating"),
        "inner_diameter": gp("inner_diameter"),
        "wall_thickness": gp("wall_thickness"),
        "needs_spec_parse": needs_spec_parse,
        "unit": unit_clean,
        "price": price,
        "tax_price": tax_price,
        "category": category,
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
    }


def ensure_dwd(es_host: str, dwd_index: str):
    session = get_es_client(es_host)
    resp = session.head(f"{es_host}/{dwd_index}")
    if resp.status_code == 404:
        print(f"  [ETL] 创建索引 {dwd_index} ...")
        session.put(f"{es_host}/{dwd_index}", json=DWD_MAPPING)
        print(f"  [ETL] 索引 {dwd_index} 创建完成")


def bulk_index(es_host: str, index: str, docs: list, ids: list = None, mark_done: bool = False) -> tuple:
    if not docs:
        return 0, 0
    if mark_done:
        for doc in docs:
            doc["needs_spec_parse"] = False
    session = get_es_client(es_host)
    body = ""
    for i, doc in enumerate(docs):
        action = {"index": {}}
        if ids and ids[i]:
            action["index"]["_id"] = ids[i]
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


def flush_to_dws(es_host: str, city: str, cfg: dict, batch_size: int = 500) -> tuple:
    """
    同步 DWD → DWS。

    入池条件（需同时满足）：
      1. needs_spec_parse = False
      2. 至少有一个细分字段（ATTR_FIELDS）非空

    同步到 DWS 时：
      - DWD 的扁平细分字段 → DWS 的 attr nested 字段
      - 重新计算 etl_time（DWS 层时间戳）

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
                ]
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

    ensure_dwd(es_host, dwd_idx)

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
        "query": {"match_all": {}},
        "size": min(batch_size, total),
        "sort": [{"update_date": "asc"}],
    }

    if category and not (incremental and since_date):
        body["query"] = {"term": {"category": category}}

    if incremental and since_date:
        if category:
            body["query"] = {"bool": {"must": [{"term": {"category": category}}]}}
        else:
            body["query"] = {"range": {"update_date": {"gte": since_date}}}

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

    while hits:
        pages += 1
        docs = []
        doc_ids = []

        for h in hits:
            try:
                doc = transform_doc(h["_source"], ods_idx, city)
                if dry_run:
                    print(f"    [dry-run] {doc['breed_clean']} → {doc['category']}")
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
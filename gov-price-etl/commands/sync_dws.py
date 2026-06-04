#!/usr/bin/env python3
"""sync_dws.py - DWD 层 → DWS 层字段映射同步（多城市）

用法:
    python3 sync_dws.py                   # 同步所有城市
    python3 sync_dws.py --city sichuan    # 只同步指定城市
    python3 sync_dws.py --dry-run         # 预览模式
"""

import json
import time
import sys
import os
import argparse

try:
    import requests
except ImportError:
    print("pip3 install requests")
    sys.exit(1)

ES_HOST = os.environ.get("ES_HOST", "http://localhost:59200")

# 城市配置
CITY_CONFIGS = {
    "xian": {"dwd": "dwd_xian_price", "dws": "dws_xian_price"},
    "sichuan": {"dwd": "dwd_sichuan_price", "dws": "dws_sichuan_price"},
    "chongqing": {"dwd": "dwd_chongqing_price", "dws": "dws_chongqing_price"},
    "jinan": {"dwd": "dwd_jinan_price", "dws": "dws_jinan_price"},
    "rizhao": {"dwd": "dwd_rizhao_price", "dws": "dws_rizhao_price"},
}

# 顶级有效字段（空值不写入）
VALID_TOP_FIELDS = [
    "unit", "price", "tax_price",
    "category",
    "province", "city", "county", "update_date", "period",
]

# 全部细分字段 → 写入 attr（空值不同步）
ATTR_FIELDS = [
    # 尺寸字段
    "thickness", "length", "width", "height", "diameter",
    "ring_stiffness", "pressure",
    # 材质/规格属性
    "material", "color", "grade",
    "voltage", "current", "cross_section",
    # 专业属性
    "asphalt_type", "cement_content",
    # 设备属性
    "channels", "doors", "cores",
    # 光纤/变送器
    "fiber_core", "length_range",
    "media", "range", "output", "cable_length",
    "temp_range", "humidity_range",
    # 扩展字段
    "surface", "series", "fire_rating", "temperature",
    "height_range",
    "installation_type", "drain_type", "inlet_type",
    # 新增字段
    "form", "ip_rating", "inner_diameter", "wall_thickness",
]

# DWS mapping
DWS_MAPPING = {
    "mappings": {
        "properties": {
            "breed": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "spec": {"type": "keyword"},
            "unit": {"type": "keyword"},
            "price": {"type": "float"},
            "tax_price": {"type": "float"},
            "category": {"type": "keyword"},
            "province": {"type": "keyword"},
            "city": {"type": "keyword"},
            "county": {"type": "keyword"},
            "update_date": {"type": "date"},
            "period": {"type": "text"},
            "attr": {"type": "object", "enabled": True},
        }
    },
    "settings": {"number_of_shards": 1, "number_of_replicas": 0}
}


def _is_non_empty(v):
    if v is None:
        return False
    if isinstance(v, str) and v.strip() == "":
        return False
    if v == 0 or v == "0":
        return False
    return True


def _strip_prefix(v):
    if isinstance(v, str) and (v.startswith('DN') or v.startswith('Φ')):
        return v[2:]
    return v


def _build_spec(doc: dict) -> str:
    l = doc.get("length", "")
    w = doc.get("width", "")
    t = doc.get("thickness", "")
    h = doc.get("height", "")
    d_orig = doc.get("diameter", "")
    p_orig = doc.get("pressure", "")
    d = _strip_prefix(d_orig)
    parts = []
    for val in [l, w, t, h, d]:
        if _is_non_empty(val):
            parts.append(str(val))
    pn = _strip_prefix(p_orig) if _is_non_empty(p_orig) else ""
    if len(parts) >= 2:
        spec = "×".join(parts)
        if pn:
            spec = pn + " " + spec
        return spec
    if parts:
        if _is_non_empty(d_orig):
            spec = (d_orig if d_orig.startswith(("DN", "Φ")) else
                    "DN" + parts[0] if d_orig.startswith("DN") else "Φ" + parts[0])
        else:
            sc = doc.get("spec", "")
            spec = sc if _is_non_empty(sc) and sc != "/" else parts[0]
        if pn:
            spec = pn + " " + spec
        return spec
    if pn:
        return pn
    sc = doc.get("spec", "")
    return sc if _is_non_empty(sc) else ""


def filter_doc(doc: dict) -> dict:
    result = {}
    breed_clean = doc.get("breed_clean")
    result["breed"] = breed_clean if _is_non_empty(breed_clean) else (doc.get("breed", "") or "")
    spec = _build_spec(doc)
    if spec:
        result["spec"] = spec
    for k in VALID_TOP_FIELDS:
        v = doc.get(k)
        if _is_non_empty(v):
            result[k] = v
    attr = {}
    for k in ATTR_FIELDS:
        v = doc.get(k)
        if _is_non_empty(v):
            attr[k] = v
    if attr:
        result["attr"] = attr
    return result


def ensure_dws(es_host: str, dws_index: str):
    session = requests.Session()
    resp = session.head(f"{es_host}/{dws_index}")
    if resp.status_code == 404:
        print(f"  [DWS] 创建索引 {dws_index} ...")
        session.put(f"{es_host}/{dws_index}", json=DWS_MAPPING)
        print(f"  [DWS] 索引创建完成")


def sync_city(es_host: str, city: str, dwd_index: str, dws_index: str,
              batch_size: int = 1000, dry_run: bool = False) -> int:
    """同步单个城市，返回同步条数"""
    ensure_dws(es_host, dws_index)

    session = requests.Session()
    count_resp = session.get(f"{es_host}/{dwd_index}/_count")
    if count_resp.status_code != 200:
        print(f"  [DWS] {city}: 索引 {dwd_index} 不存在，跳过")
        return 0

    total = count_resp.json()["count"]
    if total == 0:
        print(f"  [DWS] {city}: {dwd_index} 为空，跳过")
        return 0

    print(f"  [DWS] {city}: {dwd_index} ({total:,} 条) → {dws_index}")

    body = {"size": batch_size, "query": {"bool": {"must": [{"exists": {"field": "spec"}}]}}}
    resp = session.get(f"{es_host}/{dwd_index}/_search?scroll=1m", json=body)
    if resp.status_code != 200:
        print(f"  [DWS] {city}: 查询失败")
        return 0

    data = resp.json()
    scroll_id = data.get("_scroll_id")
    hits = data["hits"]["hits"]

    copied = 0

    while hits:
        bulk_body = ""
        for h in hits:
            doc_id = h["_id"]
            doc = filter_doc(h["_source"])
            if dry_run:
                print(f"    [dry-run] {doc.get('breed','')} spec={doc.get('spec','')}")
                continue
            action = {"index": {"_id": doc_id}}
            bulk_body += json.dumps(action, ensure_ascii=False) + "\n"
            bulk_body += json.dumps(doc, ensure_ascii=False) + "\n"

        if not dry_run:
            r = session.post(f"{es_host}/{dws_index}/_bulk",
                              data=bulk_body.encode("utf-8"),
                              headers={"Content-Type": "application/x-ndjson"})
            result = r.json()
            ok = sum(1 for item in result.get("items", []) if "error" not in item.get("index", {}))
            copied += ok

        if copied > 0 and copied % 10000 == 0:
            print(f"    已同步 {copied:,}/{total:,}")

        resp = session.post(f"{es_host}/_search/scroll",
                            json={"scroll": "1m", "scroll_id": scroll_id})
        if resp.status_code != 200:
            break
        data = resp.json()
        hits = data["hits"]["hits"]
        scroll_id = data.get("_scroll_id")

    if scroll_id:
        session.delete(f"{es_host}/_search/scroll", json={"scroll_id": scroll_id})

    if not dry_run:
        dws_count = session.get(f"{es_host}/{dws_index}/_count").json()["count"]
        print(f"  [DWS] {city} 完成: {copied:,} 条 (DWS 总计: {dws_count:,})")
    else:
        print(f"  [DWS] {city} dry-run 完成: 预览 {copied} 条")

    return copied


def run_all(es_host: str, cities: list, batch_size: int = 1000, dry_run: bool = False):
    total = 0
    for city in cities:
        if city not in CITY_CONFIGS:
            print(f"[DWS] 未知城市: {city}，跳过")
            continue
        cfg = CITY_CONFIGS[city]
        print(f"\n[DWS] 同步城市: {city}")
        n = sync_city(es_host, city, cfg["dwd"], cfg["dws"],
                      batch_size=batch_size, dry_run=dry_run)
        total += n
    print(f"\n[DWS] 全部完成: {total:,} 条")
    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DWD → DWS 多城市同步")
    parser.add_argument("--city", default="", help="指定城市（空=全部）")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.city:
        cities = [args.city] if args.city in CITY_CONFIGS else []
        if not cities:
            print(f"可用城市: {', '.join(CITY_CONFIGS.keys())}")
            sys.exit(1)
    else:
        cities = list(CITY_CONFIGS.keys())

    print(f"[DWS] ES: {ES_HOST}")
    print(f"[DWS] 城市: {', '.join(cities)}")
    print(f"[DWS] 模式: {'dry-run' if args.dry_run else '同步'}")

    start = time.time()
    run_all(ES_HOST, cities, batch_size=args.batch_size, dry_run=args.dry_run)
    print(f"[DWS] 耗时 {time.time()-start:.1f}s")
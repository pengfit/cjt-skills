#!/usr/bin/env python3
"""Minimal standalone ETL for xian"""
import sys, os, json, time, requests

ES_HOST = 'http://localhost:59200'
ODS = 'ods_material_xian_price'
DWD = 'dwd_xian_price'
DWS = 'dws_xian_price'

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

sys.path.insert(0, '/Users/pengfit/.openclaw/workspace/skills/gov-price-etl/commands')

def transform_doc_raw(src, ods_idx, city):
    from classify import classify_breed
    from parse_spec import parse_spec
    from clean import clean_breed, clean_unit, clean_price

    breed_raw = src.get("breed", "")
    spec_raw = src.get("spec", "")
    price_val = clean_price(src.get("price"))
    tax_price_val = clean_price(src.get("tax_price"))
    unit_val = clean_unit(src.get("unit", ""))
    province_val = src.get("province", "")
    county_val = src.get("county", "")
    update_date_val = src.get("update_date", "")
    create_time_val = src.get("create_time", "")

    breed_clean_val = clean_breed(breed_raw) if breed_raw else ""
    category_val = classify_breed(breed_clean_val, spec_raw, city) if breed_clean_val else "其他"

    needs_parse = True
    attr = {}
    if spec_raw and spec_raw not in ("/", ""):
        result = parse_spec(spec_raw)
        if result and result.get("parsed"):
            needs_parse = False
            attr = result.get("attr", {})
        else:
            attr = {"original": spec_raw}
    else:
        attr = {}

    doc = {
        "breed_clean": breed_clean_val,
        "spec": spec_raw,
        "spec_clean": spec_raw,
        "category": category_val,
        "price": price_val,
        "tax_price": tax_price_val,
        "unit": unit_val,
        "province": province_val,
        "city": city,
        "county": county_val,
        "update_date": update_date_val,
        "etl_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "needs_spec_parse": needs_parse,
        "source_index": ods_idx,
    }
    for k, v in attr.items():
        if k != "original":
            doc[k] = v
    return doc

def bulk_index_raw(es_host, index, docs, ids=None):
    if not docs:
        return 0, 0
    body = ""
    for i, doc in enumerate(docs):
        action = {"index": {}}
        if ids and i < len(ids) and ids[i]:
            action["index"]["_id"] = ids[i]
        body += json.dumps(action, ensure_ascii=False) + "\n"
        body += json.dumps(doc, ensure_ascii=False) + "\n"
    resp = requests.post(f"{es_host}/{index}/_bulk",
                         data=body.encode("utf-8"),
                         headers={"Content-Type": "application/x-ndjson"},
                         timeout=(30, 300))
    result = resp.json()
    errors = sum(1 for item in result.get("items", []) if "error" in item.get("index", {}))
    return len(docs) - errors, errors

def ensure_indices():
    template_body = {
        "index_patterns": ["dwd_*"],
        "template": {
            "settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": {
                "properties": {
                    "breed_clean": {"type": "keyword"}, "spec": {"type": "keyword"},
                    "spec_clean": {"type": "text"}, "category": {"type": "keyword"},
                    "price": {"type": "float"}, "tax_price": {"type": "float"},
                    "unit": {"type": "keyword"}, "province": {"type": "keyword"},
                    "city": {"type": "keyword"}, "county": {"type": "keyword"},
                    "update_date": {"type": "keyword"}, "etl_time": {"type": "date"},
                    "needs_spec_parse": {"type": "boolean"}, "source_index": {"type": "keyword"},
                    "diameter": {"type": "keyword"}, "thickness": {"type": "keyword"},
                    "length": {"type": "keyword"}, "width": {"type": "keyword"},
                    "height": {"type": "keyword"}, "material": {"type": "keyword"},
                    "grade": {"type": "keyword"}, "pressure": {"type": "keyword"},
                    "ring_stiffness": {"type": "keyword"}, "cores": {"type": "keyword"},
                    "voltage": {"type": "keyword"}, "cross_section": {"type": "keyword"},
                    "attr": {"type": "nested", "properties": {
                        "diameter": {"type": "keyword"}, "thickness": {"type": "keyword"},
                        "length": {"type": "keyword"}, "width": {"type": "keyword"},
                        "height": {"type": "keyword"}, "material": {"type": "keyword"},
                        "grade": {"type": "keyword"}, "pressure": {"type": "keyword"},
                        "ring_stiffness": {"type": "keyword"}, "cores": {"type": "keyword"},
                        "voltage": {"type": "keyword"}, "current": {"type": "keyword"},
                        "cross_section": {"type": "keyword"},
                    }}
                }
            }
        }
    }
    requests.put(f"{ES_HOST}/_index_template/gov_dwd", json=template_body)
    requests.put(f"{ES_HOST}/_index_template/gov_dws", json={
        "index_patterns": ["dws_*"],
        "template": {"settings": {"number_of_shards": 1}, "mappings": {"properties": {
            "breed_clean": {"type": "keyword"}, "spec_clean": {"type": "text"},
            "category": {"type": "keyword"}, "price": {"type": "float"},
            "tax_price": {"type": "float"}, "unit": {"type": "keyword"},
            "province": {"type": "keyword"}, "city": {"type": "keyword"},
            "county": {"type": "keyword"}, "date": {"type": "keyword"},
            "etl_time": {"type": "date"}, "attr": {"type": "nested"}
        }}}
    })
    for idx in [DWD, DWS]:
        if requests.get(f"{ES_HOST}/{idx}").status_code == 404:
            requests.put(f"{ES_HOST}/{idx}", json={})

log("Creating indices...")
ensure_indices()
log("Indices ready")

session = requests.Session()

body = {
    "query": {"bool": {"must": [{"match_all": {}}], "must_not": [{"terms": {"spec": ["/", ""]}}]}},
    "size": 500,
    "sort": [{"update_date": "asc"}],
}

log("Starting ETL...")
t0 = time.time()

t1 = time.time()
resp = session.post(f"{ES_HOST}/{ODS}/_search?scroll=2m", json=body, timeout=(10,120))
log(f"Initial search done in {time.time()-t1:.1f}s, status={resp.status_code}")

d = resp.json()
hits = d["hits"]["hits"]
scroll_id = d.get("_scroll_id", "")
total = d["hits"]["total"]["value"]
log(f"Got {len(hits)} hits, total={total}")

etled = 0
failed = 0
pages = 0

while hits:
    pages += 1
    
    # Transform
    t_tfm = time.time()
    docs, doc_ids = [], []
    for h in hits:
        try:
            doc = transform_doc_raw(h["_source"], ODS, "xian")
            if not doc.get("spec") or doc["spec"] == "/":
                continue
            docs.append(doc)
            doc_ids.append(h["_id"])
        except Exception as e:
            failed += 1
    log(f"  Page {pages}: transformed {len(docs)} docs in {time.time()-t_tfm:.1f}s, etled so far={etled}")

    # Bulk index
    if docs:
        t_bulk = time.time()
        ok, fail = bulk_index_raw(ES_HOST, DWD, docs, doc_ids)
        etled += ok
        failed += fail
        log(f"  bulk_index: ok={ok}, fail={fail} in {time.time()-t_bulk:.1f}s")

    if pages >= 3:
        log(f"  Stopping after 3 pages for now")
        break

    # Scroll
    t_scr = time.time()
    resp = session.post(f"{ES_HOST}/_search/scroll?scroll=2m",
                        json={"scroll_id": scroll_id}, timeout=(10,60))
    log(f"  Scroll {pages+1}: status={resp.status_code} in {time.time()-t_scr:.1f}s")
    
    if resp.status_code != 200:
        log(f"Scroll error: {resp.text[:100]}")
        break
    d = resp.json()
    hits = d["hits"]["hits"]
    scroll_id = d.get("_scroll_id", "")

    if not hits:
        log("No more hits")
        break

    log(f"  Total elapsed: {time.time()-t0:.0f}s")

if scroll_id:
    try:
        session.delete(f"{ES_HOST}/_search/scroll", json={"scroll_id": scroll_id})
    except:
        pass

log(f"DONE: etled={etled}, failed={failed}, pages={pages}, elapsed={time.time()-t0:.1f}s")
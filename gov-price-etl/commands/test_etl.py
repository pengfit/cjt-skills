#!/usr/bin/env python3
"""Quick test ETL for xian"""
import sys, os, json, time, requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from etl import get_es_client, transform_doc, bulk_index, ensure_indices

ES_HOST = 'http://localhost:59200'
ODS = 'ods_material_xian_price'
DWD = 'dwd_xian_price'
DWS = 'dws_xian_price'

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

log("Setup indices...")
ensure_indices(ES_HOST, {"ods": ODS, "dwd": DWD, "dws": DWS})

session = get_es_client(ES_HOST)

body = {
    "query": {"bool": {"must": [{"match_all": {}}], "must_not": [{"terms": {"spec": ["/", ""]}}]}},
    "size": 500,
    "sort": [{"update_date": "asc"}],
}

log("Initial scroll...")
t0 = time.time()
resp = session.post(f"{ES_HOST}/{ODS}/_search?scroll=2m", json=body, timeout=(10,120))
d = resp.json()
hits = d["hits"]["hits"]
scroll_id = d.get("_scroll_id", "")
total = d["hits"]["total"]["value"]
log(f"Got {len(hits)} hits, total={total}, scroll_id={scroll_id[:30]}")

etled = 0
failed = 0
pages = 0
pages_without_output = 0

while hits:
    pages += 1
    docs, doc_ids = [], []
    for h in hits:
        try:
            doc = transform_doc(h["_source"], ODS, "xian")
            if not doc.get("spec") or doc["spec"] == "/":
                continue
            docs.append(doc)
            doc_ids.append(h["_id"])
        except Exception as e:
            failed += 1

    if docs:
        ok, fail = bulk_index(ES_HOST, DWD, docs, doc_ids)
        etled += ok
        failed += fail

    if pages % 5 == 0 or etled < 1000:
        log(f"  page={pages}, etled={etled}/{total}, elapsed={time.time()-t0:.0f}s")

    # Scroll next
    resp = session.post(f"{ES_HOST}/_search/scroll?scroll=2m",
                        json={"scroll_id": scroll_id}, timeout=(10,60))
    if resp.status_code != 200:
        log(f"Scroll error {resp.status_code}: {resp.text[:100]}")
        break
    d = resp.json()
    hits = d["hits"]["hits"]
    scroll_id = d.get("_scroll_id", "")

    if not hits:
        log("No more hits, ending")
        break

if scroll_id:
    try:
        session.delete(f"{ES_HOST}/_search/scroll", json={"scroll_id": scroll_id})
    except:
        pass

log(f"DONE: etled={etled}, failed={failed}, pages={pages}, elapsed={time.time()-t0:.1f}s")
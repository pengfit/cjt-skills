#!/usr/bin/env python3
"""
flush_dws_fast.py - 直接用本地规则库重新解析 DWD，批量更新 DWS。
不走 AI，比 etl.py 的 flush_to_dws_with_ai 快 100x。
"""
import sys
import os
import json
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from parse_spec import get_parser

ES = "http://localhost:59200"


def get_dwd_scroll():
    """scroll 拿全量 DWD 文档"""
    body = {"size": 1000, "query": {"match_all": {}}}
    req = urllib.request.Request(
        f"{ES}/dwd_chongqing_price/_search?scroll=1m",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read())
    sid = d.get("_scroll_id")
    yield d["hits"]["hits"]
    while True:
        body = {"scroll": "1m", "scroll_id": sid}
        req = urllib.request.Request(
            f"{ES}/_search/scroll",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read())
        sid = d.get("_scroll_id")
        hits = d.get("hits", {}).get("hits", [])
        if not hits:
            break
        yield hits
    if sid:
        try:
            urllib.request.urlopen(urllib.request.Request(
                f"{ES}/_search/scroll",
                data=json.dumps({"scroll_id": sid}).encode(),
                headers={"Content-Type": "application/json"},
                method="DELETE"))
        except: pass


def parse_one(parser, h):
    """对单条 DWD 调用本地解析，返回 (doc_id, attr_list)"""
    src = h["_source"]
    spec = src.get("spec", "")
    breed = src.get("breed_clean") or src.get("breed", "")
    category = src.get("category", "")
    if not spec or spec == "/":
        return h["_id"], []
    parsed = parser.parse(spec, breed, category)
    attrs = [{"k": k, "v": v} for k, v in parsed.items() if v]
    return h["_id"], attrs


def bulk_update_dws(updates):
    """批量更新 DWS attr 字段"""
    if not updates:
        return 0
    lines = []
    for doc_id, attrs in updates:
        # 检查文档是否存在
        # 直接用 update doc_as_upsert
        action = {"update": {"_id": doc_id, "_index": "dws_chongqing_price"}}
        doc = {"doc": {"attr": attrs}, "doc_as_upsert": True}
        lines.append(json.dumps(action, ensure_ascii=False))
        lines.append(json.dumps(doc, ensure_ascii=False))
    body = ("\n".join(lines) + "\n").encode("utf-8")
    req = urllib.request.Request(
        f"{ES}/_bulk?refresh=false",
        data=body,
        headers={"Content-Type": "application/x-ndjson"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read())
    errs = d.get("errors", False)
    if errs:
        items = d.get("items", [])
        fail = sum(1 for it in items if it.get("update", {}).get("error"))
        print(f"  bulk update errors: {fail}/{len(items)}")
    return len(updates)


def main():
    parser = get_parser("chongqing")
    print("fetching DWD...")
    all_hits = []
    for page in get_dwd_scroll():
        all_hits.extend(page)
    print(f"DWD total: {len(all_hits)}")

    print("parsing with local rules (parallel)...")
    updates = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(parse_one, parser, h) for h in all_hits]
        for i, f in enumerate(as_completed(futures), 1):
            doc_id, attrs = f.result()
            if attrs:
                updates.append((doc_id, attrs))
            if i % 500 == 0:
                print(f"  parsed {i}/{len(all_hits)}, with_attr={len(updates)}")

    print(f"parsed: {len(updates)} docs with attr (out of {len(all_hits)})")

    # 统计
    cnt = Counter()
    for _, attrs in updates:
        for a in attrs:
            cnt[a["k"]] += 1
    print(f"\nattr 分布 (TOP 20):")
    for k, v in sorted(cnt.items(), key=lambda x: -x[1])[:20]:
        print(f"  {k:25} {v:5}")

    # 批量写 DWS
    print(f"\nwriting {len(updates)} updates to DWS...")
    BATCH = 500
    wrote = 0
    for i in range(0, len(updates), BATCH):
        batch = updates[i:i + BATCH]
        bulk_update_dws(batch)
        wrote += len(batch)
        print(f"  {wrote}/{len(updates)} written")
    # refresh
    urllib.request.urlopen(f"{ES}/dws_chongqing_price/_refresh")
    print("done.")


if __name__ == "__main__":
    main()

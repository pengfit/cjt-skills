"""DWD → DWS 快速同步(跳过 AI 解析,只同步已有 attr 的文档)

行为:
- 遍历 dwd_{city}_price 索引
- 对每条文档,_build_attr 提取出非空 attr 的才同步到 dws_{city}_price
- attr 为空的文档跳过(等规则库/AI 补全后再处理)
- 不调任何 AI 服务,纯本地操作

用法:
    python3 commands/sync_dws_quick.py [--city xian] [--batch-size 1000] [--dry-run]
"""
import argparse
import json
import os
import sys
import time

import yaml
import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from etl import _build_attr, _flat_attr_to_nested, CITY_CONFIGS, get_es_client, ensure_indices


def bulk_index(es_host, index, docs, ids, timeout=60):
    if not docs:
        return 0, 0
    body = ''
    for doc, doc_id in zip(docs, ids):
        body += json.dumps({"index": {"_index": index, "_id": doc_id}}, ensure_ascii=False) + '\n'
        body += json.dumps(doc, ensure_ascii=False) + '\n'
    try:
        resp = requests.post(
            f"{es_host}/_bulk",
            data=body.encode('utf-8'),
            headers={"Content-Type": "application/x-ndjson"},
            timeout=timeout,
        )
        if resp.status_code in (200, 201):
            items = resp.json().get('items', [])
            written = sum(1 for it in items if it.get('index', {}).get('result') in ('created', 'updated'))
            errors = sum(1 for it in items if it.get('index', {}).get('error'))
            return written, errors
    except Exception as e:
        print(f"  [ERROR] bulk_index: {e}")
    return 0, len(docs)


def sync_dws_quick(es_host, city, cfg, batch_size=1000, dry_run=False):
    dwd_idx = cfg['dwd']
    dws_idx = cfg['dws']
    session = get_es_client(es_host)

    if not dry_run:
        ensure_indices(es_host, cfg)

    # 总数
    cnt = session.post(f"{es_host}/{dwd_idx}/_count", json={"query": {"match_all": {}}}, timeout=30)
    total = cnt.json().get('count', 0)
    print(f"  [DWS-QUICK] {city}: {dwd_idx} → {dws_idx} (DWD 共 {total:,} 条)")

    synced = 0
    skipped_no_attr = 0
    failed = 0
    start = time.time()

    body = {"size": batch_size, "query": {"match_all": {}}, "sort": [{"etl_time": "asc"}, {"_id": "asc"}]}
    resp = session.post(f"{es_host}/{dwd_idx}/_search", json=body, timeout=60)
    if resp.status_code != 200:
        print(f"  [DWS-QUICK] 搜索失败: {resp.text[:200]}")
        return 0, 0, 0
    hits = resp.json()["hits"]["hits"]
    pages = 0

    while hits:
        pages += 1
        dws_docs = []
        dws_ids = []

        for h in hits:
            doc_id = h["_id"]
            d = dict(h["_source"])
            attr = _build_attr(d)
            if not attr:
                skipped_no_attr += 1
                continue
            nested = _flat_attr_to_nested(attr)
            d["attr"] = nested
            for f in list(d.keys()):
                if f.startswith("attr_"):
                    d.pop(f)
            for f in ("date", "publish_time"):
                if not d.get(f):
                    d.pop(f, None)
            dws_docs.append(d)
            dws_ids.append(doc_id)

        if dws_docs:
            if dry_run:
                synced += len(dws_docs)
            else:
                ok, err = bulk_index(es_host, dws_idx, dws_docs, dws_ids)
                synced += ok
                failed += err

        # search_after 翻页
        last = hits[-1]
        last_sort = last.get("sort")
        if not last_sort:
            break
        body["search_after"] = last_sort
        resp = session.post(f"{es_host}/{dwd_idx}/_search", json=body, timeout=60)
        if resp.status_code != 200:
            print(f"  [DWS-QUICK] 翻页失败: {resp.text[:200]}")
            break
        hits = resp.json()["hits"]["hits"]

    elapsed = time.time() - start
    print(f"  [DWS-QUICK] {city}: synced={synced}, skipped_no_attr={skipped_no_attr}, failed={failed}, 用时 {elapsed:.1f}s ({pages} 页)")
    return synced, skipped_no_attr, failed


def main():
    parser = argparse.ArgumentParser(description="DWD→DWS 快速同步（跳过 AI）")
    parser.add_argument("--city", default="", help="指定城市,空=全部")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cfg_path = os.path.join(os.path.dirname(SCRIPT_DIR), "config.yml")
    with open(cfg_path) as f:
        config = yaml.safe_load(f)
    es_host = config["es"]["host"]

    if args.city:
        cities = [args.city] if args.city in CITY_CONFIGS else []
    else:
        cities = list(CITY_CONFIGS.keys())

    if not cities:
        print(f"未知城市: {args.city}")
        sys.exit(1)

    print(f"[DWS-QUICK] ES: {es_host}")
    print(f"[DWS-QUICK] 城市: {', '.join(cities)}")
    print(f"[DWS-QUICK] 模式: {'dry-run' if args.dry_run else '正式同步'}")
    print(f"[DWS-QUICK] 策略: DWD attr 非空 → 同步;attr 空 → 跳过（等 AI 补全）")

    total_synced = total_skipped = total_failed = 0
    for city in cities:
        cfg = CITY_CONFIGS[city]
        s, sk, f = sync_dws_quick(es_host, city, cfg, batch_size=args.batch_size, dry_run=args.dry_run)
        total_synced += s
        total_skipped += sk
        total_failed += f

    print(f"\n[DWS-QUICK] 全部完成: synced={total_synced}, skipped_no_attr={total_skipped}, failed={total_failed}")


if __name__ == "__main__":
    main()

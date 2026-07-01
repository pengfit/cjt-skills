#!/usr/bin/env python3
"""refresh_dws_categories.py - 按 DB 最新规则刷新 DWS 文档的分类字段

适用：DB 规则更新后（如 manual_v3.11），但 DWS 历史文档还是旧分类。
  一次性把 DWS 文档的 category_l1/l2/l3 + name_l1/l2/l3 字段按新规则重写。

策略：
  1) 扫 DB 全部 breed_clean → (l3, name_l1/l2/l3) 映射（按 confidence DESC 排序）
  2) 扫 DWS 所有 breed_clean，按 lookup 重算分类字段
  3) bulk update DWS 文档

注意：
  - 只重写 category_l1/l2/l3 + category_name_l1/l2/l3 六个字段
  - 不动其他字段（保留所有原数据）
  - 如果新规则与原规则一致 → 跳过
"""
import argparse
import sys
import sqlite3
from pathlib import Path
from collections import defaultdict
from elasticsearch import Elasticsearch, helpers

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from gov_price_etl.config import CITY_CONFIGS, load_config  # noqa


def build_lookup(conn):
    """breed_clean → (l3, name_l1/l2/l3) 映射，按 confidence DESC 取最优。"""
    rows = conn.execute("""
        SELECT breed_clean, l3, confidence, source
        FROM breed_l3_map_v3
        ORDER BY confidence DESC, breed_clean
    """).fetchall()
    lookup = {}
    for b, l3, conf, src in rows:
        if b in lookup:
            continue
        # 查 category_v3 取 name_l1/l2/l3（注意：l1/l2/l3 是分字段存的）
        # l3='01.05.07' → category_v3 WHERE l3='01.05.07' AND l2='01.05' AND l1='01'
        l1, l2, l3_full = l3[:2], l3, l3
        if l3.count('.') >= 2:
            l1 = l3.split('.')[0]
            l2 = '.'.join(l3.split('.')[:2])
            l3_full = l3
        c = conn.execute(
            "SELECT name_l1, name_l2, name_l3 FROM category_v3 WHERE l1=? AND l2=? AND l3=? LIMIT 1",
            (l1, l2, l3_full)
        ).fetchone()
        if c is None:
            continue
        lookup[b] = {
            "category_l1": l1,
            "category_l2": l2 if l2 else "",
            "category_l3": l3_full,
            "category_name_l1": c[0] or "",
            "category_name_l2": c[1] or "",
            "category_name_l3": c[2] or "",
        }
    return lookup


def refresh_index(es, index: str, lookup: dict, batch_size: int = 2000):
    """扫 DWS 所有文档，按 lookup 重算分类字段，bulk update。"""
    print(f"\n[refresh] {index}")
    total = es.count(index=index).get("count", 0)
    print(f"  total: {total:,}")
    if total == 0:
        return 0, 0

    actions = []
    updated = 0
    no_change = 0
    no_breed = 0
    scanned = 0
    last_sort = None
    while True:
        body = {
            "size": batch_size,
            "query": {"match_all": {}},
            "sort": [{"_id": "asc"}],
            "_source": ["breed", "breed_clean",
                        "category_l1", "category_l2", "category_l3",
                        "category_name_l1", "category_name_l2", "category_name_l3"],
        }
        if last_sort:
            body["search_after"] = last_sort
        r = es.search(index=index, body=body, ignore_unavailable=True)
        hits = r.get("hits", {}).get("hits", [])
        if not hits:
            break
        for h in hits:
            src = h["_source"]
            # 优先 breed_clean（标准化后），其次 breed
            b = src.get("breed_clean") or src.get("breed") or ""
            new = lookup.get(b)
            if new is None:
                no_breed += 1
                continue
            # 比对是否需要更新
            old = {
                "category_l1": src.get("category_l1", ""),
                "category_l2": src.get("category_l2", ""),
                "category_l3": src.get("category_l3", ""),
                "category_name_l1": src.get("category_name_l1", ""),
                "category_name_l2": src.get("category_name_l2", ""),
                "category_name_l3": src.get("category_name_l3", ""),
            }
            if all(str(old.get(k, "")) == str(new.get(k, "")) for k in old):
                no_change += 1
                continue
            actions.append({
                "_op_type": "update",
                "_index": index,
                "_id": h["_id"],
                "doc": new,
            })
            updated += 1
        scanned += len(hits)
        last_sort = hits[-1].get("sort")
        print(f"    scanned {scanned:,}/{total:,} updated={updated} no_change={no_change} no_breed={no_breed}", flush=True)
        if len(hits) < batch_size:
            break

    if actions:
        try:
            helpers.bulk(es, actions, raise_on_error=True, chunk_size=batch_size, request_timeout=120)
            print(f"  ✓ bulk updated {len(actions)} docs")
        except Exception as e:
            print(f"  ✗ bulk error: {e}")
    else:
        print(f"  (nothing to update)")
    return updated, no_change


def main():
    parser = argparse.ArgumentParser(description="按 DB 最新规则刷新 DWS 分类字段")
    parser.add_argument("--city", default="", help="单城")
    parser.add_argument("--cities", default="", help="多城 key")
    args = parser.parse_args()

    cfg = load_config()
    es = Elasticsearch([cfg["es"]["host"]])

    conn = sqlite3.connect(str(PROJECT_ROOT / "data" / "category_v3_rules.db"))
    lookup = build_lookup(conn)
    print(f"lookup loaded: {len(lookup)} breeds")

    if args.city:
        cities = [args.city]
    elif args.cities:
        cities = [c.strip() for c in args.cities.split(",") if c.strip()]
    else:
        cities = sorted(CITY_CONFIGS.keys())

    grand_updated = 0
    for c in cities:
        if c not in CITY_CONFIGS:
            continue
        idx = CITY_CONFIGS[c].get("dws")
        if not idx:
            continue
        u, nc = refresh_index(es, idx, lookup)
        grand_updated += u
        print(f"  {c}: updated={u}, no_change={nc}")

    print(f"\n[done] total updated: {grand_updated}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
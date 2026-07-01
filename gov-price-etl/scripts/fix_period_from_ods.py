#!/usr/bin/env python3
"""fix_period_from_ods.py - 从 ODS 反推 DWD/DWS 文档的 period_start

适用：DWD/DWS 创建时 ODS 透传字段（period/month）丢失，period_start 被压扁为单期。
通过 (breed, spec, unit, price, county) 关联 ODS 与 DWD/DWS，按 ODS 的 month 字段派生。

用法：
  ./scripts/fix_period_from_ods.py --city xian
  ./scripts/fix_period_from_ods.py --cities heze,huhehaote,xian
"""
import argparse
import sys
from pathlib import Path
from collections import defaultdict
from elasticsearch import Elasticsearch, helpers

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from gov_price_etl.config import CITY_CONFIGS, load_config  # noqa
from gov_price_etl.transform.doc import _parse_period_field  # noqa


def _derive_from_ods_doc(src: dict, granularity: str):
    """按 ODS 字段派生 period_start/end/days（与 doc.py 一致）。"""
    raw_ps = src.get("period_start") or ""
    if raw_ps:
        return raw_ps, raw_ps, 30
    _month = src.get("month") or ""
    if _month and len(_month) == 7 and _month[4] == "-":
        y, mo = _month.split("-")
        mo_int = int(mo)
        last_day = 31 if mo_int in (1,3,5,7,8,10,12) else (28 if mo_int == 2 else 30)
        return f"{y}-{int(mo):02d}-01", f"{y}-{int(mo):02d}-{last_day:02d}", last_day
    period = src.get("period") or ""
    if period:
        r = _parse_period_field(period, granularity)
        if r:
            return r
    _ud = src.get("update_date") or ""
    if _ud and len(_ud) >= 7:
        try:
            mo = int(_ud[5:7])
        except (ValueError, IndexError):
            mo = 1
        last_day = 31 if mo in (1,3,5,7,8,10,12) else (28 if mo == 2 else 30)
        return f"{_ud[:4]}-{mo:02d}-01", f"{_ud[:4]}-{mo:02d}-{last_day:02d}", last_day
    return "", "", 1


def _build_ods_index(es, ods_index: str, granularity: str):
    """扫 ODS 全部文档，按 (breed, spec, unit, price, county) → list[(period_start, end, days)]"""
    print(f"  scanning ODS: {ods_index}")
    bucket = defaultdict(list)
    last_sort = None
    scanned = 0
    while True:
        body = {
            "size": 5000,
            "query": {"match_all": {}},
            "sort": [{"_id": "asc"}],
            "_source": ["breed", "spec", "unit", "price", "county",
                        "period_start", "period", "month", "update_date"],
        }
        if last_sort:
            body["search_after"] = last_sort
        r = es.search(index=ods_index, body=body, ignore_unavailable=True)
        hits = r.get("hits", {}).get("hits", [])
        if not hits:
            break
        for h in hits:
            src = h["_source"]
            ps, pe, pd = _derive_from_ods_doc(src, granularity)
            if not ps:
                continue
            key = (src.get("breed", ""), src.get("spec", ""),
                   src.get("unit", ""), src.get("price"),
                   src.get("county", ""))
            bucket[key].append((ps, pe, pd))
        scanned += len(hits)
        last_sort = hits[-1].get("sort")
        print(f"    scanned {scanned}", flush=True)
        if len(hits) < 5000:
            break
    return bucket


def _update_dwd_dws(es, index: str, ods_bucket: dict, granularity: str):
    """扫 DWD/DWS 文档，按 key 查 ODS bucket，更新 period_start/end/days"""
    if not ods_bucket:
        return 0, 0

    print(f"  updating {index}...")
    last_sort = None
    scanned = updated = skipped = 0
    actions = []
    while True:
        body = {
            "size": 5000,
            "query": {"match_all": {}},
            "sort": [{"_id": "asc"}],
            "_source": ["breed", "spec", "unit", "price", "county", "period_start"],
        }
        if last_sort:
            body["search_after"] = last_sort
        r = es.search(index=index, body=body, ignore_unavailable=True)
        hits = r.get("hits", {}).get("hits", [])
        if not hits:
            break
        for h in hits:
            src = h["_source"]
            key = (src.get("breed", ""), src.get("spec", ""),
                   src.get("unit", ""), src.get("price"),
                   src.get("county", ""))
            matches = ods_bucket.get(key)
            if not matches:
                skipped += 1
            else:
                # 取第一条（如果有重复取第一条）
                new_ps, new_pe, new_pd = matches[0]
                if src.get("period_start") != new_ps:
                    actions.append({
                        "_op_type": "update",
                        "_index": index,
                        "_id": h["_id"],
                        "doc": {"period_start": new_ps, "period_end": new_pe, "period_days": new_pd},
                    })
                    updated += 1
                else:
                    skipped += 1
        scanned += len(hits)
        last_sort = hits[-1].get("sort")
        print(f"    scanned {scanned}, will_update={updated}, skipped(no_change/no_ods)={skipped}", flush=True)
        if len(hits) < 5000:
            break

    if actions:
        try:
            helpers.bulk(es, actions, raise_on_error=True, chunk_size=2000, request_timeout=120)
            print(f"  ✓ {index}: bulk updated {len(actions)} docs")
        except Exception as e:
            print(f"  ✗ {index}: bulk error: {e}")
    else:
        print(f"  {index}: nothing to update")
    return updated, skipped


def main():
    parser = argparse.ArgumentParser(description="从 ODS 反推 DWD/DWS 文档 period_start")
    parser.add_argument("--city", default="", help="单城")
    parser.add_argument("--cities", default="", help="多城")
    parser.add_argument("--dwd-only", action="store_true")
    parser.add_argument("--dws-only", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    es = Elasticsearch([cfg["es"]["host"]])

    if args.city:
        cities = [args.city]
    elif args.cities:
        cities = [c.strip() for c in args.cities.split(",") if c.strip()]
    else:
        print("ERROR: 请指定 --city 或 --cities")
        return 1

    for city in cities:
        if city not in CITY_CONFIGS:
            print(f"unknown city: {city}")
            continue
        ccfg = CITY_CONFIGS[city]
        ods_index = ccfg.get("ods") or ccfg.get("ods_index")
        dwd_index = ccfg.get("dwd") or ccfg.get("dwd_index")
        dws_index = ccfg.get("dws") or ccfg.get("dws_index")
        # 粒度推断
        granularity = "monthly"
        if city == "weihai":
            granularity = "quarterly"

        print(f"\n[{city}] granularity={granularity}")
        if not ods_index:
            print(f"  no ods_index, skip")
            continue

        # 1) 建 ODS 索引
        ods_bucket = _build_ods_index(es, ods_index, granularity)
        print(f"  ODS unique keys: {len(ods_bucket)}")

        # 2) 更新 DWD/DWS
        if not args.dws_only and dwd_index:
            u, s = _update_dwd_dws(es, dwd_index, ods_bucket, granularity)
            print(f"  DWD: updated={u}, skipped={s}")
        if not args.dwd_only and dws_index:
            u, s = _update_dwd_dws(es, dws_index, ods_bucket, granularity)
            print(f"  DWS: updated={u}, skipped={s}")

    print("\n[done]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
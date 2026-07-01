#!/usr/bin/env python3
"""rederive_period_start.py - 重算 DWD/DWS period_start 字段

适用场景：
  - 历史数据 period_start 错误（如 ODS 没业务期字段、ETL 从 update_date 反推月份）
  - 现在 doc.py 已经能从 ODS 的 period/month 字段正确派生
  - 但历史 DWD/DWS 数据没更新，需要一次性修复

用法：
  ./scripts/rederive_period_start.py --city heze            # 单城
  ./scripts/rederive_period_start.py --city heze --dwd-only # 只修 DWD
  ./scripts/rederive_period_start.py --cities heze,huhehaote,xian
"""
import argparse
import sys
from pathlib import Path
from collections import Counter
from elasticsearch import Elasticsearch, helpers
from elasticsearch.helpers import BulkIndexError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from gov_price_etl.config import CITY_CONFIGS, load_config  # noqa
from gov_price_etl.transform.doc import _parse_period_field  # noqa


def _derive(raw: dict, granularity: str):
    """与 doc.py 一致的派生逻辑（独立实现避免导入完整 transform 链路）"""
    raw_ps = raw.get("period_start", "")
    if raw_ps:
        return raw_ps, raw_ps, 30
    _month = raw.get("month", "")
    if _month and len(_month) == 7 and _month[4] == "-":
        y, mo = _month.split("-")
        mo_int = int(mo)
        if 1 <= mo_int <= 12:
            last_day = 31 if mo_int in (1,3,5,7,8,10,12) else (28 if mo_int == 2 else 30)
            return f"{y}-{mo:02d}-01", f"{y}-{mo:02d}-{last_day:02d}", last_day
    period = raw.get("period", "")
    if period:
        r = _parse_period_field(period, granularity)
        if r:
            return r
    _ud = raw.get("update_date", "")
    if _ud and len(_ud) >= 7:
        try:
            mo = int(_ud[5:7])
        except (ValueError, IndexError):
            mo = 1
        last_day = 31
        if mo == 2: last_day = 28
        elif mo in (4,6,9,11): last_day = 30
        return f"{_ud[:4]}-{mo:02d}-01", f"{_ud[:4]}-{mo:02d}-{last_day:02d}", last_day
    return "", "", 1


def rederive_index(es, index: str, granularity: str, batch_size: int = 2000):
    """扫描 index 所有文档，根据 source 字段重算 period_start/end/days，写回 ES"""
    print(f"\n[rederive] {index} (granularity={granularity})")

    # 1) 拉所有文档（仅 source 必要字段）
    total = es.count(index=index).get("count", 0)
    print(f"  total docs: {total}")
    if total == 0:
        return

    # 用 search_after 翻页（避免 PIT 复杂度）
    actions = []
    updated = 0
    no_change = 0
    diff_dist = Counter()  # 派生结果分布
    last_sort = None
    while True:
        q = {"match_all": {}}
        body = {
            "size": batch_size,
            "query": q,
            "sort": [{"_id": "asc"}],
            "_source": ["period_start", "period_end", "period_days", "period", "month", "update_date", "period_granularity"],
        }
        if last_sort:
            body["search_after"] = last_sort
        r = es.search(index=index, body=body, ignore_unavailable=True)
        hits = r.get("hits", {}).get("hits", [])
        if not hits:
            break
        for h in hits:
            src = h["_source"]
            new_ps, new_pe, new_pd = _derive(src, granularity)
            diff_dist[(src.get("period_start") or "", new_ps)] += 1
            if new_ps and src.get("period_start") != new_ps:
                actions.append({
                    "_op_type": "update",
                    "_index": index,
                    "_id": h["_id"],
                    "doc": {"period_start": new_ps, "period_end": new_pe, "period_days": new_pd},
                })
                updated += 1
            else:
                no_change += 1
        last_sort = hits[-1].get("sort")
        print(f"  scanned {updated + no_change}/{total} (will_update={updated})", flush=True)
        if len(hits) < batch_size:
            break

    print(f"  need update: {updated} / no_change: {no_change}")
    print(f"  top changes (old → new):")
    for (old, new), n in diff_dist.most_common(15):
        if old != new:
            print(f"    {old!r:30} → {new!r:30} ×{n}")

    # 2) bulk update
    if actions:
        print(f"  bulk updating {len(actions)} docs...")
        try:
            helpers.bulk(es, actions, raise_on_error=True, chunk_size=batch_size, request_timeout=120)
        except BulkIndexError as e:
            print(f"  bulk errors: {len(e.errors)}")
            print(f"  first error: {e.errors[0]}")
        print(f"  ✓ {index} updated")
    else:
        print(f"  (nothing to update)")


def main():
    parser = argparse.ArgumentParser(description="重算 DWD/DWS period_start 字段")
    parser.add_argument("--city", default="", help="单城 key")
    parser.add_argument("--cities", default="", help="多城 key，逗号分隔")
    parser.add_argument("--dwd-only", action="store_true", help="只修 DWD")
    parser.add_argument("--dws-only", action="store_true", help="只修 DWS")
    parser.add_argument("--batch-size", type=int, default=2000)
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

    for c in cities:
        if c not in CITY_CONFIGS:
            print(f"unknown city: {c}")
            continue
        city_cfg = CITY_CONFIGS[c]
        dwd_index = city_cfg.get("dwd") or city_cfg.get("dwd_index")
        dws_index = city_cfg.get("dws") or city_cfg.get("dws_index")
        # 粒度从 skill config 推断（与 trend API 一致）
        granularity = "monthly"
        if c in ("weihai",):
            granularity = "quarterly"

        if not args.dws_only and dwd_index:
            rederive_index(es, dwd_index, granularity, batch_size=args.batch_size)
        if not args.dwd_only and dws_index:
            rederive_index(es, dws_index, granularity, batch_size=args.batch_size)
    print("\n[done]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
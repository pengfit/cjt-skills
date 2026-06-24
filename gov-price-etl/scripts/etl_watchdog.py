#!/usr/bin/env python3
"""ETL 守护：监控 breed_l3_map_v3 新增规则 → 触发增量补漏

背景：v3 规则库持续被 AI/手动补充，但 ETL 是按 ODS update_date 增量跑。
      当规则后补时，已入库的 ODS 文档不会被重 ETL → DWD 缺失。
      本守护通过扫 created_at 增量，触发"对历史 ODS 重跑"。

用法：
  # 一次性补漏：对所有城市的漏 ETL _id 重跑当前规则库
  python3 scripts/etl_watchdog.py once [--city CITY|--all]

  # 守护模式：每 5 分钟扫一次
  python3 scripts/etl_watchdog.py daemon --interval 300

  # 列出各城市漏 ETL 现状
  python3 scripts/etl_watchdog.py status

依赖：
  - elasticsearch 客户端
  - gov_price_etl.transform.doc.transform_doc
  - gov_price_etl.es_client.bulk_index
"""
import sys
import os
import time
import json
import sqlite3
import argparse
from pathlib import Path
from collections import Counter
from datetime import datetime

# 让脚本能 import gov_price_etl
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from elasticsearch import Elasticsearch
from gov_price_etl.config import CITY_CONFIGS, load_config
from gov_price_etl.transform.doc import transform_doc
from gov_price_etl.es_client import bulk_index
from gov_price_etl.pipeline.dws_sync import sync_dws_with_ai  # noqa: E402

DB_PATH = PROJECT_ROOT / "data" / "category_v3_rules.db"
STATE_FILE = Path.home() / ".etl_watchdog_state.json"


def get_es() -> Elasticsearch:
    cfg = load_config()
    return Elasticsearch(cfg["es"]["host"])


def get_rule_breeds(db_path: Path = DB_PATH) -> dict:
    """读 v3 规则库，返回 {breed_clean: (l3, source, confidence, created_at)}"""
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT breed_clean, l3, source, confidence, created_at FROM breed_l3_map_v3"
    ).fetchall()
    conn.close()
    return {r[0]: {"l3": r[1], "source": r[2], "confidence": r[3], "created_at": r[4]} for r in rows}


def get_ods_index_for_city(city: str) -> str:
    return CITY_CONFIGS[city]["ods"]


def get_dwd_index_for_city(city: str) -> str:
    return CITY_CONFIGS[city]["dwd"]


def get_dws_index_for_city(city: str) -> str:
    return CITY_CONFIGS[city]["dws"]


def scan_etl_gap(es: Elasticsearch, city: str) -> dict:
    """对比 ODS vs DWD，返回漏 ETL _id 集合和 DWD 孤儿 _id 集合
    漏 ETL 拆解：
      - dirty: 脏数据（spec 或 breed 为空/"/"），ETL 主动过滤
      - uncat: 走 etl 循环但 db_exact/db_fuzzy 未命中（需 AI 兜底或人工补规则）
    """
    ods_idx = get_ods_index_for_city(city)
    dwd_idx = get_dwd_index_for_city(city)
    ods_total = es.count(index=ods_idx)["count"]
    dwd_total = es.count(index=dwd_idx)["count"]

    def all_ids(idx):
        ids = []
        after = None
        while True:
            body = {"size": 0, "aggs": {"ids": {"composite": {
                "size": 5000, "sources": [{"_id": {"terms": {"field": "_id"}}}]
            }}}}
            if after:
                body["aggs"]["ids"]["composite"]["after"] = after
            r = es.search(index=idx, body=body)
            buckets = r["aggregations"]["ids"]["buckets"]
            if not buckets:
                break
            ids.extend(b["key"]["_id"] for b in buckets)
            after = r["aggregations"]["ids"].get("after_key")
            if not after or len(buckets) < 5000:
                break
        return set(ids)

    ods_ids = all_ids(ods_idx)
    dwd_ids = all_ids(dwd_idx)
    miss_ids = list(ods_ids - dwd_ids)

    # 拆解漏 ETL：脏数据 vs 真正 uncategorized
    dirty_count = 0
    if miss_ids:
        r = es.count(index=ods_idx, body={"query": {"bool": {"must": [
            {"ids": {"values": miss_ids[:10000]}}
        ], "must_not": [
            {"terms": {"spec.keyword": ["", "/"]}},
            {"terms": {"breed.keyword": ["", "/"]}}
        ]}}})
        clean_miss_count = r["count"]
        dirty_count = len(miss_ids) - clean_miss_count

    return {
        "city": city,
        "ods_total": ods_total,
        "dwd_total": dwd_total,
        "miss": miss_ids,
        "miss_count": len(miss_ids),
        "miss_dirty": dirty_count,
        "miss_uncat": len(miss_ids) - dirty_count,
        "orphan": list(dwd_ids - ods_ids),
    }


def fetch_ods_docs(es: Elasticsearch, ods_idx: str, doc_ids: list, chunk: int = 1000):
    """按 _id 批量拉 ODS 文档（避免 size 限制）"""
    out = []
    for i in range(0, len(doc_ids), chunk):
        sub = doc_ids[i:i+chunk]
        # ES 一次 ids query 限 10000
        r = es.search(
            index=ods_idx,
            size=len(sub),
            _source=True,
            query={"ids": {"values": sub}},
        )
        out.extend({"_id": h["_id"], "_source": h["_source"]} for h in r["hits"]["hits"])
    return out


def transform_to_dwd(ods_docs: list, city: str, ods_idx: str) -> tuple:
    """对每条 ODS 文档跑 transform_doc，返回 (docs, doc_ids, failed_breeds)"""
    docs, doc_ids, failed_breeds = [], [], []
    for d in ods_docs:
        try:
            doc = transform_doc(d["_source"], ods_idx, city)
            v2 = doc.get("category_v2_source", "")
            if v2 in ("db_exact_v3", "db_fuzzy_v3", "ai_v3"):
                if doc.get("breed"):
                    docs.append(doc)
                    doc_ids.append(d["_id"])
                else:
                    failed_breeds.append(doc.get("breed_clean", "?"))
            else:
                failed_breeds.append(d["_source"].get("breed", "?"))
        except Exception as e:
            failed_breeds.append(d["_source"].get("breed", "?") + f" (err: {e})")
    return docs, doc_ids, failed_breeds


def backfill_city(es: Elasticsearch, city: str, dry_run: bool = False) -> dict:
    """对一个城市做"补漏"流程：
       1. 扫 ODS vs DWD 找漏 ETL _id
       2. 拉 ODS 原始文档
       3. 跑 transform_doc（走当前 v3 规则库 2 段式）
       4. 命中写 DWD
       5. 同步 DWS
    """
    cfg = CITY_CONFIGS[city]
    ods_idx = cfg["ods"]
    dwd_idx = cfg["dwd"]
    dws_idx = cfg["dws"]

    print(f"\n[backfill] {city} ({cfg['city_label']}): {ods_idx} → {dwd_idx} → {dws_idx}")
    gap = scan_etl_gap(es, city)
    print(f"  ODS={gap['ods_total']}  DWD={gap['dwd_total']}  漏 ETL={len(gap['miss'])}  孤儿={len(gap['orphan'])}")

    if not gap["miss"]:
        print(f"  无漏 ETL，跳过")
        return {"city": city, "backfilled": 0, "remaining_miss": 0}

    print(f"  拉 {len(gap['miss'])} 条 ODS 文档...")
    ods_docs = fetch_ods_docs(es, ods_idx, gap["miss"])
    print(f"  拿到 {len(ods_docs)} 条，跑 transform_doc...")
    docs, doc_ids, failed_breeds = transform_to_dwd(ods_docs, city, ods_idx)
    print(f"  命中 {len(docs)} 条，失败 {len(failed_breeds)} 条")

    if failed_breeds:
        counter = Counter(failed_breeds)
        print(f"  失败 top 5: {dict(counter.most_common(5))}")

    if docs and not dry_run:
        ok, fail = bulk_index("http://localhost:59200", dwd_idx, docs, doc_ids)
        print(f"  bulk_index → ok={ok}, fail={fail}")
    else:
        print(f"  [dry-run] 跳过 bulk_index")

    # DWS 同步（增量）
    if docs and not dry_run:
        print(f"  同步 DWS...")
        dws_ok, dws_fail = sync_dws_with_ai("http://localhost:59200", city, cfg, batch_size=500)
        print(f"  DWS 同步: ok={dws_ok}, fail={dws_fail}")

    return {
        "city": city,
        "ods_total": gap["ods_total"],
        "dwd_total_before": gap["dwd_total"],
        "miss_before": len(gap["miss"]),
        "backfilled": len(docs),
        "remaining_miss": len(failed_breeds),
    }


def cmd_status(args):
    """列出各城市漏 ETL 现状（拆解：脏数据 / 真正 uncategorized）"""
    es = get_es()
    print(f"\n=== ETL 漏 ETL 现状 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ===\n")
    print(f"{'城市':12s}  {'ODS':>7s}  {'DWD':>7s}  {'漏 ETL':>7s}  {'脏数据':>7s}  {'真uncategorized':>14s}")
    print("-" * 70)
    for city in CITY_CONFIGS:
        gap = scan_etl_gap(es, city)
        print(f"  {city:10s}  {gap['ods_total']:7d}  {gap['dwd_total']:7d}  {gap['miss_count']:7d}  "
              f"{gap['miss_dirty']:7d}  {gap['miss_uncat']:14d}")


def cmd_once(args):
    """一次性补漏"""
    es = get_es()
    cities = [args.city] if args.city else list(CITY_CONFIGS.keys())
    print(f"\n=== 一次性补漏: {cities} ===\n")
    results = []
    for city in cities:
        r = backfill_city(es, city, dry_run=args.dry_run)
        results.append(r)

    print(f"\n=== 汇总 ===")
    for r in results:
        print(f"  {r['city']:10s}  补回 {r.get('backfilled', 0):5d}  剩余未命中 {r.get('remaining_miss', 0):5d}")


def cmd_daemon(args):
    """守护模式：每 N 秒扫一次规则库"""
    es = get_es()
    interval = args.interval
    print(f"[watchdog] 启动守护模式，间隔 {interval}s")

    # 加载状态
    state = {"last_seen_created_at": ""}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
        except Exception:
            pass

    while True:
        try:
            rules = get_rule_breeds()
            if not rules:
                print(f"[watchdog] 规则库为空，等 {interval}s")
                time.sleep(interval)
                continue

            # 找增量（created_at > last_seen）
            last_seen = state.get("last_seen_created_at", "")
            new_rules = [r for r in rules.values() if r["created_at"] > last_seen]

            if new_rules:
                breeds = [r["breed_clean"] for r in new_rules if "breed_clean" in r]
                # 实际 rules dict 的 key 就是 breed_clean
                breeds = [bc for bc, r in rules.items() if r["created_at"] > last_seen]
                print(f"[watchdog] {datetime.now()}: 检测到 {len(breeds)} 条新规则，触发补漏")
                for city in CITY_CONFIGS:
                    backfill_city(es, city)
                # 更新 last_seen = max(created_at)
                state["last_seen_created_at"] = max(r["created_at"] for r in rules.values())
                STATE_FILE.write_text(json.dumps(state, indent=2))
                print(f"[watchdog] last_seen 推进到 {state['last_seen_created_at']}")
            else:
                print(f"[watchdog] {datetime.now()}: 无新规则（last_seen={last_seen}）")

            time.sleep(interval)
        except KeyboardInterrupt:
            print(f"\n[watchdog] 用户中断，退出")
            break
        except Exception as e:
            print(f"[watchdog] 错误: {e}")
            time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="ETL 守护")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_status = sub.add_parser("status", help="列出各城市漏 ETL 现状")
    p_status.set_defaults(func=cmd_status)

    p_once = sub.add_parser("once", help="一次性补漏")
    p_once.add_argument("--city", default="", help="指定城市（空=全部）")
    p_once.add_argument("--dry-run", action="store_true", help="预览模式")
    p_once.set_defaults(func=cmd_once)

    p_daemon = sub.add_parser("daemon", help="守护模式（每 N 秒扫一次）")
    p_daemon.add_argument("--interval", type=int, default=300, help="间隔秒数（默认 300）")
    p_daemon.set_defaults(func=cmd_daemon)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

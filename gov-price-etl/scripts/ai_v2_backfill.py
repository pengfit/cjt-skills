#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai_v2_backfill.py - v2 阶段 4 AI 攒批回写脚本

背景：
  v2 5 段式分类（db_exact_v2 / db_fuzzy_v2 / pattern_v2 / fallback_v2），
  5 段式都未命中的品种（fallback_v2 / no_match_v2）由阶段 4 AI 兜底。
  本脚本扫所有 DWD 文档找这些品种 → 攒批调 AI → update_by_query 写回。

触发条件（默认）：
  category_v2_source in ['fallback_v2', 'no_match_v2', 'error_v2']
  且 category_l3 = '' 或 'UNCLASSIFIED'

用法：
    python3 scripts/ai_v2_backfill.py --dry-run     # 列出待回写品种
    python3 scripts/ai_v2_backfill.py --cities heze # 指定城市
    python3 scripts/ai_v2_backfill.py --limit 20    # 限制每个城市回写条数（测试用）
"""

import argparse
import sys
import time
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from elasticsearch import Elasticsearch

from gov_price_etl.config import CITY_CONFIGS
from gov_price_etl.ai.service import classify_v2_batch, get_stats as get_ai_stats
from gov_price_etl.classify.category_v2 import close_singleton as close_v2_singleton


ES_HOST = "http://localhost:59200"

# 触发回写的源标记
REPAIR_SOURCES = ("fallback_v2", "no_match_v2", "error_v2")


def find_pending_breeds(es, dwd_idx: str, limit: int = 1000) -> list:
    """
    找 DWD 索引里 v2 分类"未命中"的品种（按 breed_clean 去重）。

    返回: [{"breed": ..., "spec": ..., "unit": ..., "breed_clean": ...}, ...]
    """
    seen = set()
    pending = []
    # 滚动分页
    body = {
        "size": 500,
        "_source": ["breed", "breed_clean", "spec", "unit", "category_v2_source", "category_l3"],
        "query": {
            "terms": {"category_v2_source": list(REPAIR_SOURCES)}
        },
        "sort": [{"etl_time": "asc"}],
    }
    res = es.search(index=dwd_idx, body=body)
    for h in res["hits"]["hits"]:
        s = h["_source"]
        bc = s.get("breed_clean", "")
        if not bc or bc in seen:
            continue
        seen.add(bc)
        pending.append({
            "breed": s.get("breed", ""),
            "breed_clean": bc,
            "spec": s.get("spec", ""),
            "unit": s.get("unit", ""),
        })
        if len(pending) >= limit:
            break
    return pending


def backfill_one_city(es, city: str, dwd_idx: str, limit: int, dry_run: bool) -> dict:
    """回写单个城市的 v2 字段。返回 {ok, failed, skipped}。"""
    pending = find_pending_breeds(es, dwd_idx, limit=limit)
    print(f"\n=== [{city}] dwd={dwd_idx} ===")
    print(f"  待回写品种（去重）: {len(pending)}")
    if not pending:
        return {"ok": 0, "failed": 0, "skipped": 0}
    if dry_run:
        for i, it in enumerate(pending[:10]):
            print(f"  [{i+1}] {it['breed']} | spec={it['spec']} | unit={it['unit']}")
        if len(pending) > 10:
            print(f"  ... +{len(pending) - 10} more")
        return {"ok": 0, "failed": 0, "skipped": len(pending), "dry_run": True}

    # 攒批调 AI
    t0 = time.time()
    ai_results = classify_v2_batch(pending, city=city, write_rules=True)
    elapsed = time.time() - t0
    print(f"  AI 调 AI 耗时: {elapsed:.1f}s")
    ok = fail = skip = 0
    # 按 breed_clean update_by_query 写回 v2 字段
    for item in pending:
        bc = item["breed_clean"]
        v2 = ai_results.get(bc)
        if not v2 or not v2.get("l3"):
            skip += 1
            continue
        # update_by_query：按 breed_clean 匹配
        update_body = {
            "query": {"term": {"breed_clean": bc}},
            "script": {
                "lang": "painless",
                "source": _build_painless_source(v2),
                "params": v2,
            },
        }
        r = es.update_by_query(
            index=dwd_idx,
            body=update_body,
            refresh=True,
            conflicts="proceed",
        )
        n = r.get("updated", 0)
        if n > 0:
            ok += n
        else:
            fail += 1
    return {"ok": ok, "failed": fail, "skipped": skip}


def _build_painless_source(v2: dict) -> str:
    """生成 painless 脚本源码：把 v2 字段赋值给 ctx._source。"""
    lines = []
    field_map = {
        "category_l1": "l1", "category_l2": "l2", "category_l3": "l3",
        "category_l4": "l4", "category_name_l1": "name_l1",
        "category_name_l2": "name_l2", "category_name_l3": "name_l3",
        "eng_part": "eng_part", "eng_stage": "eng_stage",
        "main_or_aux": "main_or_aux", "gb_50500": "gb_50500",
        "quota_ref": "quota_ref", "ifc_class": "ifc_class",
        "uniclass_ss": "uniclass_ss", "material_code": "material_code",
        "category_v2_source": "category_v2_source",
        "category_v2_confidence": "category_v2_confidence",
    }
    for dwd_field, v2_key in field_map.items():
        lines.append(f"ctx._source.{dwd_field} = params.{v2_key};")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="v2 阶段 4 AI 攒批回写")
    parser.add_argument("--cities", nargs="+", default=None,
                        help=f"指定城市（默认全部），可用: {', '.join(CITY_CONFIGS.keys())}")
    parser.add_argument("--limit", type=int, default=200,
                        help="每个城市回写上限（默认 200）")
    parser.add_argument("--dry-run", action="store_true", help="只列出待回写品种")
    args = parser.parse_args()

    close_v2_singleton()  # v2 单例重置

    es = Elasticsearch([ES_HOST])
    cities = args.cities or list(CITY_CONFIGS.keys())
    print(f"回写范围: {', '.join(cities)}  (每城 limit={args.limit}, dry_run={args.dry_run})")

    total_ok = total_fail = total_skip = 0
    for city in cities:
        cfg = CITY_CONFIGS[city]
        dwd_idx = cfg["dwd"]
        r = backfill_one_city(es, city, dwd_idx, limit=args.limit, dry_run=args.dry_run)
        if "dry_run" in r:
            print(f"  [DRY-RUN] 跳过 {r['skipped']} 条")
        else:
            print(f"  ✓ 更新 {r['ok']} 条 / 失败 {r['failed']} / 跳过 {r['skipped']}")
            total_ok += r["ok"]
            total_fail += r["failed"]
            total_skip += r["skipped"]

    print(f"\n=== 总计 ===")
    if not args.dry_run:
        print(f"  更新: {total_ok} / 失败: {total_fail} / 跳过: {total_skip}")
        print(f"  AI stats: {get_ai_stats()}")


if __name__ == "__main__":
    main()

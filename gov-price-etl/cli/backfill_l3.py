#!/usr/bin/env python3
"""cli/backfill_l3 - 给 breed_spec_rules.db 中 l3 为空的规则回填 L3

策略：
1. 按 breed_clean 查 ES（DWD/DWS 索引），拿 category_name_l3
2. 按 (breed_clean, pattern) 反查 DWD，找到该 pattern 实际命中的 doc 的 L3
3. 两种都失败 → 留空（接受无 L3 加权）

用法：
  ./cli/backfill_l3.py --dry-run              # 预览，不写库
  ./cli/backfill_l3.py --limit 100            # 试跑 100 条
  ./cli/backfill_l3.py                       # 全量回填
  ./cli/backfill_l3.py --city weihai          # 只回填该城市用过的规则
"""
import argparse
import json
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path
from urllib.request import urlopen, Request

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from gov_price_etl.config import load_config  # noqa: E402
from gov_price_etl.parse_spec.rules.vector_store import get_vec_store, SPEC_RULES_DB  # noqa: E402


def es_query(es_host: str, index: str, body: dict, timeout: int = 30) -> dict:
    """ES 简易查询封装。"""
    req = Request(
        f"{es_host}/{index}/_search",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def build_breed_to_l3(es_host: str, cities: list = None, sample_per_breed: int = 1) -> dict:
    """扫描 DWS/DWD，建 breed_clean → category_name_l3 映射。

    多城市都查，取出现最多的 L3（多数投票）。
    """
    cfg = load_config()
    es_host = es_host or cfg["es"]["host"]

    # 找所有 dwd_* 索引
    pattern = "dwd_*_price" if not cities else f"dwd_{cities[0]}_price"
    indices = []
    if cities:
        indices = [f"dwd_{c}_price" for c in cities]
    else:
        # 列出所有 dwd_*_price 索引
        req = Request(f"{es_host}/_cat/indices/dwd_*_price?format=json")
        try:
            with urlopen(req, timeout=15) as r:
                indices = [x["index"] for x in json.loads(r.read())]
        except Exception as e:
            print(f"[WARN] 拉索引列表失败: {e}")
            return {}

    print(f"[1/3] 扫描 {len(indices)} 个 DWD 索引...")

    breed_l3_counter = defaultdict(lambda: defaultdict(int))
    for idx in indices:
        try:
            r = es_query(es_host, idx, {
                "size": 0,
                "aggs": {
                    "by_breed": {
                        # breed_clean / category_l3 在 mapping 里本身就是 keyword,不要再加 .keyword
                        "terms": {"field": "breed_clean", "size": 5000},
                        "aggs": {
                            "by_l3": {
                                # v0.7+: L3 必须用编码(XX.XX.XX),不用 category_name_l3(中文名)
                                "terms": {"field": "category_l3", "size": 5}
                            }
                        }
                    }
                }
            })
        except Exception as e:
            print(f"  [SKIP] {idx}: {e}")
            continue

        for breed_bucket in r["aggregations"]["by_breed"]["buckets"]:
            breed = breed_bucket["key"]
            for l3_bucket in breed_bucket["by_l3"]["buckets"]:
                breed_l3_counter[breed][l3_bucket["key"]] += l3_bucket["doc_count"]

    # 取每个 breed 占比最高的 L3（>50% 才用，否则留空）
    breed_to_l3 = {}
    skipped = 0
    import re
    code_pattern = re.compile(r"^\d+\.\d+\.\d+$")
    for breed, l3_counter in breed_l3_counter.items():
        total = sum(l3_counter.values())
        if total == 0:
            continue
        # v0.7+: 只用 L3 编码 (XX.XX.XX),过滤掉脏数据(中文名/空)
        code_only = {k: v for k, v in l3_counter.items() if code_pattern.match(k)}
        if not code_only:
            skipped += 1
            continue
        top_l3, top_count = max(code_only.items(), key=lambda x: x[1])
        if top_count / total >= 0.5:
            breed_to_l3[breed] = top_l3
        else:
            skipped += 1
    print(f"  breed → L3(编码) 映射: {len(breed_to_l3)} 条（{skipped} 个 breed L3 分散或全为中文,跳过）")
    return breed_to_l3


def backfill(dry_run: bool = False, limit: int = 0, cities: list = None) -> dict:
    """回填主入口。"""
    cfg = load_config()
    es_host = cfg["es"]["host"]
    vs = get_vec_store()
    conn = vs._get_conn()

    # 1. 建 breed → L3 映射
    breed_to_l3 = build_breed_to_l3(es_host, cities)

    # 2. 扫所有 l3 为空的规则
    print(f"\n[2/3] 扫规则库...")
    cur = conn.execute(
        "SELECT id, pattern, attr, breed, category, l3 "
        "FROM breed_spec_rules "
        "WHERE (l3 IS NULL OR l3='') "
        "ORDER BY id"
    )
    rules = cur.fetchall()
    if limit > 0:
        rules = rules[:limit]
    print(f"  待回填: {len(rules)} 条")

    # 3. 回填
    print(f"\n[3/3] 回填中（dry_run={dry_run}）...")
    by_breed = defaultdict(int)
    by_empty_breed = 0
    filled = 0
    skipped = 0
    t0 = time.time()
    for rid, pattern, attr, breed, category, _ in rules:
        target_l3 = ""
        # 策略 A：直接按 breed_clean 查
        if breed and breed in breed_to_l3:
            target_l3 = breed_to_l3[breed]
            by_breed[breed] += 1
        elif not breed:
            by_empty_breed += 1
            # 策略 B：按 pattern 试匹配一条 DWD doc
            # （高级场景：留空，避免误回填）

        if target_l3:
            if not dry_run:
                conn.execute(
                    "UPDATE breed_spec_rules SET l3=? WHERE id=?",
                    (target_l3, rid),
                )
            filled += 1
        else:
            skipped += 1

        if (filled + skipped) % 200 == 0 and (filled + skipped) > 0:
            print(f"  进度: {filled + skipped}/{len(rules)}, filled={filled}, skipped={skipped}, "
                  f"elapsed={time.time()-t0:.1f}s")

    if not dry_run:
        conn.commit()

    # 4. 报告
    print()
    print("=" * 50)
    print("回填结果:")
    print(f"  总规则: {len(rules)}")
    print(f"  ✓ 已回填: {filled} ({filled/len(rules)*100:.1f}%)")
    print(f"  - 跳过: {skipped} ({skipped/len(rules)*100:.1f}%)")
    print(f"  - 其中 breed 为空的: {by_empty_breed}")
    print(f"  耗时: {time.time()-t0:.1f}s")
    if by_breed:
        print(f"  Top 5 breed 回填数:")
        for b, c in sorted(by_breed.items(), key=lambda x: -x[1])[:5]:
            print(f"    {b}: {c}")
    print("=" * 50)
    return {
        "total": len(rules),
        "filled": filled,
        "skipped": skipped,
        "by_breed": dict(by_breed),
        "by_empty_breed": by_empty_breed,
    }


def main():
    parser = argparse.ArgumentParser(description="回填 breed_spec_rules.db 的 l3 字段")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不写库")
    parser.add_argument("--limit", type=int, default=0, help="试跑前 N 条")
    parser.add_argument("--city", action="append", help="限定城市（可多次）")
    args = parser.parse_args()

    backfill(dry_run=args.dry_run, limit=args.limit, cities=args.city)


if __name__ == "__main__":
    main()

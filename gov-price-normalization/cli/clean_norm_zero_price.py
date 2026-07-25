#!/usr/bin/env python3
"""
clean_norm_zero_price.py

清除 norm_* index 中 price 和 tax_price 都为空或0 的脏数据。

(道友 2026-07-25 11:07 反馈:之前 build_norm_index 没拦截 price null/0
 的 DWS 文档,导致一批空文档落到 NORM,污染跨城均价 / 热力图涨跌 / attr_norm。)

策略: ES delete_by_query 命中条件
   (price IS NULL OR price = 0) AND (tax_price IS NULL OR tax_price = 0)
匹配:

  price field: missing / null  / 0  → 不命中(只要有一条 price 合法就保留)

清理逻辑:
  - 扫所有 norm_*_price 索引
  - 每一索引单独报告 count + sample _id
  - --yes 才会真删(默认 dry-run)

用法:
  python3 cli/clean_norm_zero_price.py            # 报告每个索引的脏数据条数 (dry-run)
  python3 cli/clean_norm_zero_price.py --yes     # 真删,逐索引确认后批量
  python3 cli/clean_norm_zero_price.py --index norm_xian_price  # 只清单一索引
"""
from __future__ import annotations
import os
import sys
import json
import argparse
from typing import List, Dict

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# defer
ES_HOST = os.environ.get("ES_HOST", "http://localhost:59200")


def _connect(host):
    from elasticsearch import Elasticsearch
    return Elasticsearch(host, verify_certs=False)


def _list_norm_indices(es) -> List[str]:
    """扫所有 norm_*_price 索引。"""
    pat = "norm_*_price"
    indices: List[str] = []
    try:
        # 兼容 ES Python client 8.x (返回 list[str]) 与 老版本 (返回 list[dict])
        result = es.indices.get(index=pat, expand_wildcards="open", ignore_unavailable=True)
        for item in result:
            if isinstance(item, str):
                name = item
            elif isinstance(item, dict):
                name = item.get("index", "")
            else:
                continue
            if name.startswith("norm_") and name.endswith("_price"):
                indices.append(name)
    except Exception as e:
        sys.stderr.write(f"[warn] list_norm_indices failed: {e}\n")
    return sorted(set(indices))


def _count_dirty(es, index: str) -> int:
    """统计 price+tax_price 都为 missing/0 的文档数。

    2026-07-25 修复: "term: {field: null}" 在 ES 7/8 mapping=double 时报
       parsing_exception,被 catch 静默返回 0(误判为干净)。
    改成 bool/should + must_not exists + term 0。
    """
    q = {
        "query": {
            "bool": {
                "must": [
                    {"bool": {"should": [
                        {"bool": {"must_not": {"exists": {"field": "price"}}}},
                        {"term": {"price": 0}},
                    ], "minimum_should_match": 1}},
                    {"bool": {"should": [
                        {"bool": {"must_not": {"exists": {"field": "tax_price"}}}},
                        {"term": {"tax_price": 0}},
                    ], "minimum_should_match": 1}},
                ]
            }
        }
    }
    try:
        r = es.count(index=index, body=q, ignore_unavailable=True, allow_no_indices=True)
        return int(r.get("count", 0))
    except Exception as e:
        sys.stderr.write(f"  [warn] count({index}): {e}\n")
        return 0


def _sample_ids(es, index: str, n: int = 3) -> List[str]:
    q = {
        "query": {
            "bool": {
                "must": [
                    {"bool": {"should": [
                        {"bool": {"must_not": {"exists": {"field": "price"}}}},
                        {"term": {"price": 0}},
                    ], "minimum_should_match": 1}},
                    {"bool": {"should": [
                        {"bool": {"must_not": {"exists": {"field": "tax_price"}}}},
                        {"term": {"tax_price": 0}},
                    ], "minimum_should_match": 1}},
                ]
            }
        },
        "size": n,
        "_source": ["_id", "breed", "period_start"],
    }
    out = []
    try:
        r = es.search(index=index, body=q, ignore_unavailable=True, allow_no_indices=True)
        for h in r.get("hits", {}).get("hits", []):
            out.append(h.get("_id", "?"))
    except Exception as e:
        sys.stderr.write(f"  [warn] sample({index}): {e}\n")
    return out


def _delete_dirty(es, index: str) -> int:
    """ES delete_by_query 删 dirty 文档,返回实际删除数。"""
    q = {
        "query": {
            "bool": {
                "must": [
                    {"bool": {"should": [
                        {"bool": {"must_not": {"exists": {"field": "price"}}}},
                        {"term": {"price": 0}},
                    ], "minimum_should_match": 1}},
                    {"bool": {"should": [
                        {"bool": {"must_not": {"exists": {"field": "tax_price"}}}},
                        {"term": {"tax_price": 0}},
                    ], "minimum_should_match": 1}},
                ]
            }
        }
    }
    try:
        r = es.delete_by_query(
            index=index,
            body=q,
            conflicts="proceed",
            refresh=True,
            ignore_unavailable=True,
            allow_no_indices=True,
            slices="auto",
        )
        return int(r.get("deleted", 0))
    except Exception as e:
        sys.stderr.write(f"  [err] delete({index}): {e}\n")
        return 0


def main():
    ap = argparse.ArgumentParser(
        description="清除 norm_* 中 price+tax_price 都为 null/0 的脏文档"
    )
    ap.add_argument("--es-host", default=ES_HOST, help="ES 地址")
    ap.add_argument("--yes", action="store_true", help="真删(默认只 dry-run 统计)")
    ap.add_argument("--index", help="只清单一索引(默认扫全部 norm_*_price)")
    ap.add_argument("--limit", type=int, default=0, help="最多清前 N 个索引(0=全清)")
    args = ap.parse_args()

    es = _connect(args.es_host)

    if args.index:
        indices = [args.index]
    else:
        indices = _list_norm_indices(es)
    print(f"[scan] 命中 {len(indices)} 个 norm_*_price 索引")
    if not indices:
        print("✅ 没有 norm 索引,无需清理")
        return 0

    # 1. dry-run scan 全部
    summary: Dict[str, int] = {}
    for idx in indices:
        n = _count_dirty(es, idx)
        summary[idx] = n
        if n > 0:
            samples = _sample_ids(es, idx, n=3)
            print(f"  {idx}: {n} 脏文档  sample _ids={samples}")
        else:
            print(f"  {idx}: 0 脏文档")

    total = sum(summary.values())
    print(f"\n[scan] 共 {total} 个脏文档")
    if total == 0:
        print("✅ 没有需要清理的脏数据")
        return 0

    if args.yes:
        print(f"\n[confirm] ⚠️ 即将从以上索引删除 {total} 个脏文档 ...")
    else:
        print(f"\n[dry-run] 加 --yes 参数真删。")
        return 0

    # 2. 真删
    deleted_total = 0
    err_count = 0
    for idx, n in summary.items():
        if n == 0:
            continue
        if args.limit and deleted_total >= args.limit:
            print(f"[limit] 已达到 limit={args.limit},停止")
            break
        d = _delete_dirty(es, idx)
        print(f"  {idx}: deleted {d}")
        if d == 0 and n > 0:
            err_count += 1
        deleted_total += d
    print(f"\n[done] 实际删除 {deleted_total},失败 {err_count}")
    return 0 if err_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
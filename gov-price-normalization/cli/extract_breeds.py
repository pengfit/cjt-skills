#!/usr/bin/env python3
"""extract_breeds.py — 从 NORM 索引抽 distinct breed by L3

输出 tmp/breeds_by_l3.json，喂给 LLM（OpenClaw / Dify / 外部）做 canonical mapping。

用法：
    # 全量抽（扫所有 norm_*_price）
    python3 -m cli.extract_breeds

    # 单城
    python3 -m cli.extract_breeds --cities xian,hainan

    # 只输出未在已有 canonical mapping 里出现的 breed（增量模式）
    python3 -m cli.extract_breeds --incremental \
        --canonical data/breed_canonical.json \
        --out tmp/pending_breeds.json

    # 只输出没有 L3 code 的（unmapped 候选）
    python3 -m cli.extract_breeds --no-l3-only --out tmp/breeds_no_l3.json
"""

from __future__ import annotations
import sys
import json
import argparse
from pathlib import Path
from collections import defaultdict

_HERE = Path(__file__).resolve().parent
_PKG = _HERE.parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from elasticsearch import Elasticsearch

ES_HOST = "http://localhost:59200"


def list_norm_indices(es) -> list[str]:
    """扫所有 norm_*_price 索引。"""
    resp = es.indices.get(index="norm_*_price", ignore_unavailable=True)
    return sorted(resp.keys())


def extract_breeds(es, indices: list[str], size_per_l3: int = 1000) -> dict:
    """从一组 NORM 索引抽 distinct breed by L3。

    使用字段：
      - breed (keyword)         raw_breed
      - breed_clean (text)      ETL 已清理过的名字
      - category_l3 (text)      GB 50500 L3 码
      - category_name_l3 (text) GB 50500 L3 名

    Returns:
        {
          "by_l3": {
            "<category_l3>": {
              "name_l3": str or None,
              "breeds": [str, ...],
              "doc_count": int,
            },
            ...
          },
          "no_l3": [str, ...],
          "total": int,
        }
    """
    by_l3: dict = defaultdict(lambda: {"name_l3": None, "breeds": set(), "doc_count": 0})
    no_l3: set = set()
    total = 0

    for idx in indices:
        try:
            r = es.search(
                index=idx,
                body={
                    "size": 0,
                    "aggs": {
                        "by_l3_breed": {
                            "terms": {"field": "category_l3.keyword", "size": 200},
                            "aggs": {
                                "name_l3": {"terms": {"field": "category_name_l3.keyword", "size": 1}},
                                "breeds": {"terms": {"field": "breed", "size": size_per_l3}}
                            }
                        },
                        "no_l3_breeds": {
                            "missing": {"field": "category_l3.keyword"},
                            "aggs": {
                                "breeds": {"terms": {"field": "breed", "size": size_per_l3}}
                            }
                        }
                    }
                },
                ignore_unavailable=True,
            )
        except Exception as e:
            print(f"[warn] {idx} skip: {e}", file=sys.stderr)
            continue

        aggs = r.get("aggregations", {})

        # by_l3
        for l3_bucket in aggs.get("by_l3_breed", {}).get("buckets", []):
            l3_code = l3_bucket["key"]
            entry = by_l3[l3_code]
            entry["doc_count"] += l3_bucket["doc_count"]
            # name_l3 取出现最多的
            nl3_buckets = l3_bucket.get("name_l3", {}).get("buckets", [])
            if nl3_buckets and not entry["name_l3"]:
                entry["name_l3"] = nl3_buckets[0]["key"]
            for b_bucket in l3_bucket.get("breeds", {}).get("buckets", []):
                entry["breeds"].add(b_bucket["key"])
                total += b_bucket["doc_count"]

        # no_l3
        for b_bucket in aggs.get("no_l3_breeds", {}).get("breeds", {}).get("buckets", []):
            no_l3.add(b_bucket["key"])

    by_l3_out = {}
    for l3_code, info in by_l3.items():
        by_l3_out[l3_code] = {
            "name_l3": info["name_l3"],
            "doc_count": info["doc_count"],
            "breeds": sorted(info["breeds"]),
        }
    return {
        "by_l3": dict(sorted(by_l3_out.items())),
        "no_l3": sorted(no_l3),
        "total": total,
    }


def filter_against_canonical(data: dict, canonical: dict) -> dict:
    """增量模式：只保留不在已有 canonical mapping 里的 breed。"""
    # 收集已映射的所有 raw_breed（不分 L3）
    mapped_raws = set()
    for l3_info in canonical.get("by_l3", {}).values():
        for raw_list in l3_info.get("canonical_map", {}).values():
            for raw in raw_list:
                mapped_raws.add(raw)
    # unmapped_seen 也算"已处理"
    unmapped_seen = set(canonical.get("unmapped_seen", {}).keys())

    out_by_l3 = {}
    total_new = 0
    for l3_code, info in data["by_l3"].items():
        new_breeds = [b for b in info["breeds"] if b not in mapped_raws and b not in unmapped_seen]
        if new_breeds:
            out_by_l3[l3_code] = {
                "name_l3": info["name_l3"],
                "doc_count": info["doc_count"],
                "breeds": new_breeds,
            }
            total_new += len(new_breeds)
    new_no_l3 = [b for b in data["no_l3"] if b not in mapped_raws and b not in unmapped_seen]
    return {
        "by_l3": dict(sorted(out_by_l3.items())),
        "no_l3": new_no_l3,
        "total_new": total_new,
    }


def main():
    ap = argparse.ArgumentParser(description="从 NORM 索引抽 distinct breed by L3")
    ap.add_argument("--es-host", default=ES_HOST)
    ap.add_argument("--cities", help="逗号分隔城市列表（默认全量）")
    ap.add_argument("--out", default="tmp/breeds_by_l3.json", help="输出路径")
    ap.add_argument("--incremental", action="store_true",
                    help="增量模式：只输出未在 canonical 里的 breed")
    ap.add_argument("--canonical", default="data/breed_canonical.json",
                    help="已有 canonical mapping（增量模式用）")
    ap.add_argument("--no-l3-only", action="store_true", help="只输出没 L3 的 breed")
    ap.add_argument("--size-per-l3", type=int, default=1000)
    args = ap.parse_args()

    es = Elasticsearch(args.es_host, request_timeout=60)

    if args.cities:
        cities = [c.strip() for c in args.cities.split(",") if c.strip()]
        indices = [f"norm_{c}_price" for c in cities]
    else:
        indices = list_norm_indices(es)
    print(f"[scan] {len(indices)} indices: {indices[:3]}..." if len(indices) > 3 else f"[scan] {indices}")

    raw = extract_breeds(es, indices, size_per_l3=args.size_per_l3)
    print(f"[extract] {raw['total']} docs, {len(raw['by_l3'])} L3 codes, {len(raw['no_l3'])} unmapped")

    out_data = raw
    if args.incremental:
        try:
            canonical = json.loads(Path(args.canonical).read_text(encoding="utf-8"))
            out_data = filter_against_canonical(raw, canonical)
            print(f"[incremental] new breeds: {out_data['total_new']}")
        except FileNotFoundError:
            print(f"[warn] canonical file not found: {args.canonical}; 输出全量")

    if args.no_l3_only:
        out_data = {"by_l3": {}, "no_l3": out_data["no_l3"], "total": out_data.get("total_new", out_data["total"])}

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] {out_path}  ({out_path.stat().st_size:,} bytes)")

    # 简易预览
    print("\n=== preview (top 5 L3 by doc_count) ===")
    top5 = sorted(out_data["by_l3"].items(), key=lambda x: -x[1]["doc_count"])[:5]
    for l3_code, info in top5:
        sample = info["breeds"][:8]
        more = f" (+{len(info['breeds'])-8} more)" if len(info["breeds"]) > 8 else ""
        print(f"  {l3_code} ({info['doc_count']:,} docs, {len(info['breeds'])} breeds)")
        print(f"    示例: {sample}{more}")


if __name__ == "__main__":
    main()
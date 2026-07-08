#!/usr/bin/env python3
"""normalize_breed_format.py — breed 格式归一（不语义合并）

Step 1 of Phase B：
- 抽 NORM 所有 distinct breed
- 格式归一（去换行/空格/括号/标点/字母单位大小写）
- 输出 tmp/breed_format_map.json
- 加 --write-back 可一键 update_by_query 写 normalized_breed 字段

格式归一规则（不动语义）：
  1. 去 \n \r \t、全角空格
  2. 连续空白压成单个空格
  3. 去首尾空格
  4. 全角括号 → 半角
  5. 全角标点 → 半角（， 、 ； ： ！？）
  6. 全角破折号 → 半角 -
  7. 字母单位归一（KV → kV、MM2 → mm²、m2 → m²、m3 → m³）
  8. 数字之间的 x/X → ×
  9. Φ → φ（统一）
  10. 连续 - / × 压成一个
"""
from __future__ import annotations
import sys
import re
import json
import argparse
from pathlib import Path
from collections import defaultdict

_HERE = Path(__file__).resolve().parent
_PKG = _HERE.parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from elasticsearch import Elasticsearch, helpers

ES_HOST = "http://localhost:59200"


def normalize_breed_format(raw: str) -> str:
    """格式归一，不动语义（仅清理格式差异）。"""
    if not raw:
        return raw
    s = raw

    # 1. 去换行 / 制表 / 全角空格
    s = s.replace('\n', '').replace('\r', '').replace('\t', '')
    s = s.replace('\u3000', ' ')  # 全角空格 → 半角空格

    # 2. 连续空白压成单个
    s = re.sub(r'\s+', ' ', s)

    # 3. 去首尾空格
    s = s.strip()

    # 4. 全角括号 → 半角
    s = s.replace('（', '(').replace('）', ')')
    s = s.replace('【', '[').replace('】', ']')
    s = s.replace('〈', '<').replace('〉', '>')

    # 5. 全角标点 → 半角
    s = s.replace('，', ',').replace('、', ',')
    s = s.replace('；', ';').replace('：', ':').replace('？', '?').replace('！', '!')

    # 6. 全角破折号 → 半角
    s = s.replace('—', '-').replace('–', '-').replace('－', '-')

    # 7. 字母单位归一（注意 \b 边界，避免误伤）
    s = re.sub(r'\bKV\b', 'kV', s)
    s = re.sub(r'\bMM2\b', 'mm²', s, flags=re.IGNORECASE)
    s = re.sub(r'\bm2\b', 'm²', s)
    s = re.sub(r'\bm3\b', 'm³', s)
    s = re.sub(r'\bCM2\b', 'cm²', s, flags=re.IGNORECASE)
    s = re.sub(r'\bCM3\b', 'cm³', s, flags=re.IGNORECASE)
    s = re.sub(r'\bDN\b', 'DN', s)  # already uppercase, no-op

    # 8. 数字之间的 x/X → ×
    s = re.sub(r'(\d)\s*[xX×]\s*(\d)', r'\1×\2', s)

    # 9. Φ → φ（统一）
    s = s.replace('Φ', 'φ')

    # 10. 连续符号压成单个
    s = re.sub(r'-+', '-', s)
    s = re.sub(r'×+', '×', s)

    # 11. 再次去首尾空格（防止前面规则引入）
    s = s.strip()

    return s


def main():
    ap = argparse.ArgumentParser(description="breed 格式归一（不语义合并）")
    ap.add_argument("--es-host", default=ES_HOST)
    ap.add_argument("--out", default="tmp/breed_format_map.json")
    ap.add_argument("--write-back", action="store_true", help="update_by_query 写 normalized_breed 到 NORM")
    ap.add_argument("--max-breeds-per-idx", type=int, default=50000)
    args = ap.parse_args()

    es = Elasticsearch(args.es_host, request_timeout=60)

    # 1. 抽所有 distinct breed
    print("[step 1] 抽 distinct breed ...")
    resp = es.indices.get(index="norm_*_price", ignore_unavailable=True)
    indices = sorted(resp.keys())
    all_breeds: set = set()
    for idx in indices:
        r = es.search(
            index=idx,
            body={"size": 0, "aggs": {"b": {"terms": {"field": "breed", "size": args.max_breeds_per_idx}}}},
            ignore_unavailable=True,
        )
        cnt = 0
        for b in r['aggregations']['b']['buckets']:
            all_breeds.add(b['key'])
            cnt += 1
        print(f"  {idx}: {cnt} breeds")
    print(f"  total distinct (union): {len(all_breeds)}")

    # 2. 归一
    print("\n[step 2] 格式归一 ...")
    raw_to_norm: dict = {}
    norm_groups: dict = defaultdict(list)
    for raw in all_breeds:
        norm = normalize_breed_format(raw)
        raw_to_norm[raw] = norm
        norm_groups[norm].append(raw)

    collapsed = sum(1 for raws in norm_groups.values() if len(raws) > 1)
    no_change = sum(1 for raw, norm in raw_to_norm.items() if raw == norm)
    changed = len(raw_to_norm) - no_change
    print(f"  归一后 distinct: {len(norm_groups)}")
    print(f"  被合并组数 (>1 raw 归一同一 norm): {collapsed}")
    print(f"  无需变化的 breed: {no_change}")
    print(f"  有变化的 breed: {changed}")

    # 3. 输出映射表
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_data = {
        "_meta": {
            "version": "0.1.0",
            "method": "format_only_v1",
            "total_raw": len(all_breeds),
            "total_normalized": len(norm_groups),
            "collapsed_groups": collapsed,
            "no_change_count": no_change,
            "changed_count": changed,
        },
        "raw_to_normalized": dict(sorted(raw_to_norm.items())),
        "groups": {
            norm: sorted(raws)
            for norm, raws in sorted(norm_groups.items())
            if len(raws) > 1
        },
    }
    out_path.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[done] {out_path} ({out_path.stat().st_size:,} bytes)")

    # 4. preview top 20 合并组
    print("\n=== top 20 collapsed groups (按 raw 数倒序) ===")
    top = sorted(out_data["groups"].items(), key=lambda x: -len(x[1]))[:20]
    for norm, raws in top:
        print(f"  [{len(raws)}] → {norm}")
        for r in raws[:5]:
            print(f"        {r}")
        if len(raws) > 5:
            print(f"        ... +{len(raws)-5} more")

    # 5. 写回（可选）— 跨所有索引分批 update_by_query
    if args.write_back:
        print(f"\n[step 3] update_by_query 写 normalized_breed （跨 {len(indices)} 索引分批） ...")
        # 只处理 changed 的 raw（raw != norm）
        changed_map = {raw: norm for raw, norm in raw_to_norm.items() if raw != norm}
        print(f"  changed raws: {len(changed_map)}")
        if not changed_map:
            print("[done] no changes to write back")
            return

        # 分批（500 一批，避免 script body 超限）
        batch_size = 500
        raws = list(changed_map.keys())
        total_updated = 0
        total_failed = 0
        for i in range(0, len(raws), batch_size):
            batch_raws = raws[i:i+batch_size]
            batch_map = {r: changed_map[r] for r in batch_raws}
            try:
                r = es.update_by_query(
                    index="norm_*_price",
                    body={
                        "query": {"terms": {"breed": batch_raws}},
                        "script": {
                            "source": "if (params.map.containsKey(ctx._source.breed)) { ctx._source.normalized_breed = params.map.get(ctx._source.breed); }",
                            "lang": "painless",
                            "params": {"map": batch_map},
                        },
                    },
                    refresh=True,
                    conflicts="proceed",
                    wait_for_completion=True,
                    slices="auto",
                )
                updated = r.get("updated", 0)
                failed = r.get("failures", [])
                total_updated += updated
                total_failed += len(failed) if isinstance(failed, list) else failed
                print(f"  batch {i//batch_size+1}: raws={len(batch_raws)} updated={updated} failures={len(failed) if isinstance(failed, list) else failed}")
            except Exception as e:
                print(f"  batch {i//batch_size+1}: ERROR {e}")
                total_failed += len(batch_raws)
        print(f"\n[done] total updated: {total_updated}, failed: {total_failed}")

        # 顺手 refresh
        try:
            es.indices.refresh(index="norm_*_price")
        except Exception:
            pass
    else:
        print(f"\n[hint] 加 --write-back 参数可一键写回 NORM")


if __name__ == "__main__":
    main()
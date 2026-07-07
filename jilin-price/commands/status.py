#!/usr/bin/env python3
"""吉林 skill 状态查询：本地进度 + ES ODS 数据。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

import utils as _u


def main():
    cfg = _u.load_config()

    # 1. 本地进度
    progress_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        ".jilin_sync_progress.json",
    )
    print("=== 本地进度 ===")
    if os.path.exists(progress_path):
        import json
        with open(progress_path) as f:
            p = json.load(f)
        done = p.get("done", [])
        print(f"  已完成 {len(done)} 个 (period, diqu) 单元")
        for d in done:
            print(f"    {d}")
    else:
        print(f"  无（{progress_path} 不存在）")

    # 2. ES ODS 统计
    print("\n=== ES ODS ===")
    es = cfg["es"]
    try:
        r = requests.get(f"{es['host']}/{es['index']}/_count", timeout=10)
        print(f"  {es['index']}: {r.json().get('count', '?')} 条")
        # 按 period 聚合
        r2 = requests.post(
            f"{es['host']}/{es['index']}/_search",
            json={"size": 0, "aggs": {"by_period": {"terms": {"field": "period", "size": 30}}}},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        d = r2.json()
        buckets = d.get("aggregations", {}).get("by_period", {}).get("buckets", [])
        if buckets:
            print(f"  各期数:")
            for b in buckets:
                print(f"    {b['key']:<20s} {b['doc_count']:>6d}")
        # 按 county
        r3 = requests.post(
            f"{es['host']}/{es['index']}/_search",
            json={"size": 0, "aggs": {"by_county": {"terms": {"field": "county", "size": 20}}}},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        d3 = r3.json()
        buckets = d3.get("aggregations", {}).get("by_county", {}).get("buckets", [])
        if buckets:
            print(f"  各区县:")
            for b in buckets:
                print(f"    {b['key']:<20s} {b['doc_count']:>6d}")
    except Exception as e:
        print(f"  ✗ ES 查询失败: {e}")


if __name__ == "__main__":
    main()
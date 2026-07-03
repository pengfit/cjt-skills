"""济南工程造价材料信息 - 状态查看（v0.1, 2026-07-03）

支持新进度格式：
  - 本地：.jinan_sync_progress.json（done_<period_id>_<cat_id>: [...]）
  - ES：ods_material_jinan_price_sync_progress（每 unit 一行）
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import urllib3
import requests
from collections import Counter

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def main():
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(script_dir, 'config.yml')

    import yaml
    with open(config_path) as f:
        config = yaml.safe_load(f) or {}
    es_host = config.get('es', {}).get('host', 'http://localhost:59200')
    es_index = config.get('es', {}).get('index', 'ods_material_jinan_price')
    progress_index = config.get('es', {}).get('progress_index', 'ods_material_jinan_price_sync_progress')

    # ── 1. ES 文档总数 ──
    try:
        r = requests.get(f"{es_host}/{es_index}/_count", timeout=10, verify=False)
        count = r.json().get('count', '?')
    except Exception:
        count = '?'
    print(f"ES 文档总数 ({es_index}): {count}")

    # ── 2. ES 端进度：按 status 分组、按 period 统计 ──
    print(f"\nES 同步进度索引: {progress_index}")
    try:
        # 按 status 聚合
        r2 = requests.post(
            f"{es_host}/{progress_index}/_search",
            json={
                "size": 0,
                "aggs": {
                    "by_status": {"terms": {"field": "status", "size": 10}},
                    "by_period": {
                        "terms": {"field": "period", "size": 20, "order": {"_key": "asc"}},
                        "aggs": {"total_docs": {"sum": {"field": "docs_written"}}},
                    },
                    "total_docs": {"sum": {"field": "docs_written"}},
                },
            },
            timeout=10,
            verify=False,
        )
        aggs = r2.json().get("aggregations", {})
        print(f"  按状态分布:")
        for b in aggs.get("by_status", {}).get("buckets", []):
            print(f"    {b['key']:15s} {b['doc_count']:>5d} units")
        print(f"  按周期分布:")
        for b in aggs.get("by_period", {}).get("buckets", []):
            sub = b.get("total_docs", {}).get("value", 0)
            print(f"    {b['key']:25s} {b['doc_count']:>5d} units  ({sub:.0f} docs)")
        total = aggs.get("total_docs", {}).get("value", 0)
        print(f"  总写入文档: {total:.0f}")

        # 最近一次 run
        r3 = requests.post(
            f"{es_host}/{progress_index}/_search",
            json={"size": 1, "sort": [{"last_updated": "desc"}], "query": {"match_all": {}}},
            timeout=10, verify=False,
        )
        hits = r3.json().get("hits", {}).get("hits", [])
        if hits:
            src = hits[0]["_source"]
            print(f"\n  最近一次 unit:")
            print(f"    run_id:  {src.get('run_id', '?')}")
            print(f"    period:  {src.get('period', '?')} (id={src.get('period_id', '?')})")
            print(f"    cat:     {src.get('catalogue_name', '?')}")
            print(f"    status:  {src.get('status', '?')}")
            print(f"    docs:    {src.get('docs_written', '?')}")
            print(f"    updated: {src.get('last_updated', '?')}")
    except Exception as e:
        print(f"  读取失败: {e}")

    # ── 3. 本地进度 ──
    progress_path = os.path.join(script_dir, '.jinan_sync_progress.json')
    print(f"\n本地进度: {progress_path}")
    if os.path.exists(progress_path):
        with open(progress_path, 'r', encoding='utf-8') as f:
            prog = json.load(f)
        if not prog:
            print("  (空)")
        else:
            done_keys = [k for k in prog.keys() if k.startswith('done_') and k != 'saved_at']
            print(f"  已完成 units: {len(done_keys)}")
            # 按周期分组
            by_period: dict = {}
            for k in done_keys:
                # 格式：done_<period_id>_<cat_id>
                m = k.split('_')
                if len(m) >= 3:
                    pid = m[1]
                    by_period.setdefault(pid, 0)
                    by_period[pid] += 1
            for pid, n in by_period.items():
                print(f"    period_id={pid}: {n} cats")
            print(f"  saved_at: {prog.get('saved_at', '无')}")
    else:
        print("  (不存在)")

    # ── 4. config.yml 摘要 ──
    print(f"\nconfig.yml 摘要:")
    print(f"  year: {config.get('sync', {}).get('year', '无')}")
    print(f"  last_period: {config.get('sync', {}).get('last_period', '无')}")
    print(f"  last_run_id: {config.get('sync', {}).get('last_run_id', '无')}")
    print(f"  last_run_at: {config.get('sync', {}).get('last_run_at', '无')}")


if __name__ == '__main__':
    main()

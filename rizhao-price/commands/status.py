#!/usr/bin/env python3
"""status.py - 日照同步状态查看（v1.0 SyncRunner 化, 2026-07-03）

显示：
- ES 中 ODS 索引统计（按 tab 聚合 + period 分布）
- 本地进度（每个 tab × period 的 done 状态）
- ES progress 索引最新运行记录
- 数据范围（年份/期数）
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import warnings
warnings.filterwarnings('ignore')
from commands.utils import load_config

CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'config.yml',
)


def main():
    config = load_config(CONFIG_PATH)
    es_host = config.get('es', {}).get('host', 'http://localhost:59200')
    es_index = config.get('es', {}).get('index', 'ods_material_rizhao_price')
    progress_index = config.get('es', {}).get('progress_index', 'ods_rizhao_price_sync_progress')
    last_period = config.get('sync', {}).get('last_period', '')

    progress_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        '.rizhao_sync_progress.json'
    )
    local = {}
    if os.path.exists(progress_file):
        with open(progress_file) as f:
            local = json.load(f)

    print("=" * 60)
    print("=== 日照材料价格同步状态 (v1.0 SyncRunner) ===")
    print("=" * 60)
    print(f"ES 索引: {es_index}")
    print(f"进度索引: {progress_index}")
    print(f"上次同步期数: {last_period or '(未同步)'}")
    print("")

    # ES ODS 索引统计
    try:
        import requests
        resp = requests.post(
            f"{es_host}/{es_index}/_search",
            json={
                "size": 0,
                "aggs": {
                    "by_tab": {"terms": {"field": "tab_type", "size": 10}},
                    "by_period": {"terms": {"field": "period", "size": 20},
                                  "aggs": {
                                      "period_window": {
                                          "top_hits": {
                                              "size": 1,
                                              "_source": ["period_start", "period_end", "period_days"],
                                          }
                                      }
                                  }},
                }
            },
            timeout=15, verify=False,
        )
        if resp.status_code == 200:
            aggs = resp.json().get('aggregations', {})
            total = resp.json().get('hits', {}).get('total', {}).get('value', 0)
            print(f"── ES ODS 索引 ──")
            print(f"  总文档数: {total}")
            tabs = aggs.get('by_tab', {}).get('buckets', [])
            for b in tabs:
                print(f"  tab={b['key']}: {b['doc_count']} 条")
            print(f"\n── 期间分布 ──")
            for b in aggs.get('by_period', {}).get('buckets', []):
                hits = b.get('period_window', {}).get('hits', {}).get('hits', [])
                if hits:
                    src = hits[0]['_source']
                    print(f"  period={b['key']}: {b['doc_count']} 条 "
                          f"({src.get('period_start')} ~ {src.get('period_end')}, "
                          f"{src.get('period_days')} 天)")
            print("")
        else:
            print(f"[!] ES 查询失败: {resp.status_code}")
    except Exception as e:
        print(f"[!] 无法查询 ES: {e}")

    # 本地进度
    print("── 本地进度 ──")
    done_keys = [k for k in local.keys() if k.startswith('done_')]
    if not done_keys:
        print("  (无)")
    else:
        for k in sorted(done_keys):
            v = local[k]
            print(f"  {k}: {v.get('tab_name')} {v.get('period')} "
                  f"({v.get('period_start')}~{v.get('period_end')}, {v.get('period_days')}天) "
                  f"→ {v.get('docs_written')} 条 [{v.get('status')}]")
    print("")

    # ES progress 索引
    print("── ES progress 索引（最近 5 条）──")
    try:
        import requests
        resp = requests.post(
            f"{es_host}/{progress_index}/_search",
            json={"size": 5, "sort": [{"last_updated": "desc"}]},
            timeout=15, verify=False,
        )
        if resp.status_code == 200:
            hits = resp.json().get('hits', {}).get('hits', [])
            if hits:
                for h in hits:
                    s = h.get('_source', {})
                    print(f"  run_id={s.get('run_id')} tab={s.get('tab_type')} "
                          f"period={s.get('period')} ({s.get('period_start')}~{s.get('period_end')}, "
                          f"{s.get('period_days')}天) docs={s.get('docs_written')} "
                          f"status={s.get('status')}")
            else:
                print("  (无)")
    except Exception as e:
        print(f"  [!] 无法查询: {e}")


if __name__ == '__main__':
    main()
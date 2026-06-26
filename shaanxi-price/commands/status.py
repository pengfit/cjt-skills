"""陕西工程造价材料信息 - 状态查询

查看本地进度文件 + ES 进度索引。
"""
import argparse
import json
import os
import sys
from collections import Counter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import load_config, get_es_client
from sync import PROGRESS_FILE


def main():
    parser = argparse.ArgumentParser(description='陕西工程造价材料信息 - 状态查询')
    parser.add_argument('--es', action='store_true', help='查询 ES 索引详情')
    args = parser.parse_args()

    cfg = load_config()

    # 本地进度
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            prog = json.load(f)
        done = prog.get('done', {})
    else:
        done = {}

    ok_count = sum(1 for d in done.values() if d.get('status') == 'ok')
    fail_count = sum(1 for d in done.values() if d.get('status') == 'failed')
    partial_count = sum(1 for d in done.values() if d.get('status') == 'partial')
    skipped_count = sum(1 for d in done.values() if d.get('status') == 'skipped_image_pdf')
    print(f'[shaanxi] 本地进度: {len(done)} 期 (ok={ok_count}, partial={partial_count}, skipped={skipped_count}, failed={fail_count})')

    # 按 city + period 统计
    city_counter = Counter()
    period_counter = Counter()
    docs_total = 0
    for d in done.values():
        if d.get('status') == 'ok' or d.get('status') == 'partial':
            city_counter[d.get('city', '?')] += 1
            period_counter[d.get('period', '?')] += 1
            docs_total += d.get('docs_written', 0)
        elif d.get('status') == 'skipped_image_pdf':
            # 图像型 PDF 未入库，但仍然计入 city/period 统计（标记为未入）
            city_counter[d.get('city', '?')] += 1
            period_counter[d.get('period', '?')] += 1
    if city_counter:
        print(f'\n按 city:')
        for c, n in sorted(city_counter.items(), key=lambda x: -x[1]):
            print(f'  {c:8} {n} 期')
    if period_counter:
        print(f'\n按 period:')
        for p, n in sorted(period_counter.items()):
            print(f'  {p:25} {n} 期')
    print(f'\n总写入: {docs_total} 条')

    # 最近 5 期
    if done:
        recent = sorted(done.items(), key=lambda x: x[1].get('created_at', ''), reverse=True)[:5]
        print(f'\n最近 5 期:')
        for url, d in recent:
            print(f"  {d.get('period', '?')} | {d.get('city', '?')} | docs={d.get('docs_written', 0)} | {d.get('status', '?')} | {d.get('publish_date', '?')}")
            print(f"    {d.get('title', '')[:60]}")

    # ES 状态
    if args.es:
        try:
            es = get_es_client(cfg['es']['host'])
            ods_idx = cfg['es']['ods_index']
            prog_idx = cfg['es']['progress_index']

            if es.indices.exists(index=ods_idx):
                cnt = es.count(index=ods_idx)
                print(f'\nES [{ods_idx}]: {cnt["count"]} 条')

            if es.indices.exists(index=prog_idx):
                cnt = es.count(index=prog_idx)
                print(f'ES [{prog_idx}]: {cnt["count"]} 条')

            # 按 city 聚合
            if es.indices.exists(index=ods_idx):
                res = es.search(index=ods_idx, body={
                    'size': 0,
                    'aggs': {
                        'by_city': {'terms': {'field': 'city', 'size': 20}},
                        'by_period': {'terms': {'field': 'period', 'size': 50}},
                    },
                })
                print(f'\n按 city (ES):')
                for b in res['aggregations']['by_city']['buckets']:
                    print(f'  {b["key"]:8} {b["doc_count"]:6} 条')
                print(f'\n按 period (ES):')
                for b in res['aggregations']['by_period']['buckets']:
                    print(f'  {b["key"]:25} {b["doc_count"]:6} 条')
        except Exception as e:
            print(f'\nES 查询失败: {e}')


if __name__ == '__main__':
    main()

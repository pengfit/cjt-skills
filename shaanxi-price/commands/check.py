"""陕西工程造价材料信息 - 增量检测

只读取源站列表，对比本地进度，输出未入仓的期（不实际下载/写入）。
"""
import argparse
import os
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import load_config
from sync import fetch_all_periods, PROGRESS_FILE, load_progress

import json


def main():
    parser = argparse.ArgumentParser(description='陕西工程造价材料信息 - 增量检测')
    parser.add_argument('--year', type=int, default=0, help='年份（默认 config.sync.target_year）')
    args = parser.parse_args()

    cfg = load_config()
    if args.year == 0:
        args.year = cfg.get('sync', {}).get('target_year', datetime.now().year)

    print(f'[check] year={args.year}')

    items = fetch_all_periods(cfg)
    print(f'[check] 共 {len(items)} 期')

    progress = load_progress()
    done = progress.get('done', {})

    # 过滤
    todo = []
    skipped = []
    for it in items:
        if args.year and f'{args.year}年' not in it['title']:
            continue
        if it['detail_url'] in done and done[it['detail_url']].get('status') == 'ok':
            skipped.append(it)
            continue
        todo.append(it)

    print(f'[check] 已入仓: {len(skipped)}, 待入仓: {len(todo)}\n')

    if todo:
        print('待入仓:')
        for it in todo:
            period_d = done.get(it['detail_url'], {})
            status = period_d.get('status', 'new')
            print(f'  [{status:8}] {it["publish_date"]} | {it["title"][:70]}')
    else:
        print('✓ 全部入仓')


if __name__ == '__main__':
    main()

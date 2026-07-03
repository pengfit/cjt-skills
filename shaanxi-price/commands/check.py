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


# === dashboard status 同步（v0.8.1, 2026-07-03）===
# 捕获 main() 的 stdout，按末行 [城市] 状态写到 /tmp/gov-check-status/<key>.json
# 供 dashboard /sync 顶部 chip 复用。已存在则覆盖。
if __name__ == '__main__':
    import sys as _sys, io as _io
    _buf = _io.StringIO()
    _old_stdout = _sys.stdout
    _sys.stdout = _buf
    try:
        main()
    finally:
        _sys.stdout = _old_stdout
    _output = _buf.getvalue()
    print(_output, end='')  # 完整回放到屏幕（保留原行为）

    # 写 check_status json
    try:
        if '/Users/pengfit/.openclaw/workspace/skills/gov-price-etl' not in _sys.path:
            _sys.path.insert(0, '/Users/pengfit/.openclaw/workspace/skills/gov-price-etl')
        from gov_price_etl.check_status import write_status_from_check_output
        write_status_from_check_output('shaanxi', '陕西', _output)
    except Exception as _e:
        print(f'⚠️ check_status 失败: {_e}', file=_sys.stderr)

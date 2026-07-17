"""贵州 · 预览模式：不写入 ES / MinIO, 仅打印将处理的内容。"""
import argparse
import os
import sys
import tempfile
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from sync import (
    fetch_all_periods, parse_pdf_tables, parse_period_from_title,
)
from utils import load_config, download_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--period', default='', help='指定周期')
    parser.add_argument(
        '--year', type=int, default=None,
        help='只预览指定年份的期（默认 config.default_year=2026；0=不限制）',
    )
    parser.add_argument('--latest', action='store_true', help='只预览最新一期')
    args = parser.parse_args()

    cfg = load_config()
    items = fetch_all_periods(cfg)
    print(f'\n[preview] 共 {len(items)} 期（POST AJAX 翻页结果）')

    if args.period:
        items = [it for it in items if args.period in it['title']]
    if args.year is not None:
        items = [it for it in items if f'{args.year}年' in it['title']]
    if args.latest:
        items = items[:1]

    print(f'[preview] 过滤后 {len(items)} 期\n')

    for it in items:
        print(f'── {it["title"]} ({it["publish_date"]}) ──')
        print(f'  detail: {it["detail_url"]}')
        win = parse_period_from_title(it['title'])
        if win and not win.get('invalid'):
            print(
                f'  period: {win["period"]}  '
                f'start: {win["period_start"]}  '
                f'end: {win["period_end"]}  '
                f'days: {win["period_days"]}  '
                f'issue: {win["issue"]}'
            )
        else:
            print(f'  period: <无法解析>')

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                local = os.path.join(tmpdir, 's.pdf')
                download_file(it['pdf_url'], local, timeout=120)
                rows = parse_pdf_tables(local)
                print(f'  parsed rows: {len(rows)}')
                if rows:
                    print('  sample:')
                    for r in rows[:3]:
                        print(
                            f"    {r['breed']} | {r['spec']} | "
                            f"{r['unit']} | {r['city']} = {r['price']}"
                        )
                else:
                    print('  (无解析行 — 仍会归档 PDF 插 placeholder)')
        except Exception as e:
            print(f'  ✗ {e}')


if __name__ == '__main__':
    main()

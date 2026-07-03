"""预览模式：不写入 ES / minio，仅打印将处理的内容（v0.8, 2026-07-03）

v0.8 改造：去掉对 sync.main 的引用（已拆分到 cmd_legacy_sync + henan_collector）。
预览时也展示新字段 period_start / period_end / period_days。
"""
import argparse
import os
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from sync import (
    fetch_all_periods, parse_detail_page, parse_pdf_tables,
    extract_period_from_title,
)
from henan_collector import parse_period_window
from utils import load_config, fetch_html, download_file
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--period', default='', help='指定周期')
    parser.add_argument('--year', type=int, default=datetime.now().year, help='只预览指定年份的期（默认本年，0=不限制）')
    parser.add_argument('--latest', action='store_true', help='只预览最新一期')
    args = parser.parse_args()

    cfg = load_config()
    items = fetch_all_periods(cfg)
    print(f'\n[preview] 共 {len(items)} 期')

    if args.period:
        items = [it for it in items if args.period in it['title']]
    if args.year:
        items = [it for it in items if f'{args.year}年' in it['title']]
    if args.latest:
        items = items[:1]

    for it in items:
        print(f'\n── {it["title"]} ({it["publish_date"]}) ──')
        print(f'  detail: {it["detail_url"]}')
        try:
            html = fetch_html(it['detail_url'], timeout=cfg['site']['timeout_sec'])
            detail = parse_detail_page(html, cfg['site']['base_url'])
            print(f'  pdf: {detail["pdf_url"]}  ({detail["pdf_name"]})')
            win = parse_period_window(detail['title'] or it['title'])
            print(
                f'  period: {win["period"]}  '
                f'start: {win["period_start"]}  '
                f'end: {win["period_end"]}  '
                f'days: {win["period_days"]}  '
                f'months: {win["months"]}'
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                local = os.path.join(tmpdir, 's.pdf')
                download_file(detail['pdf_url'], local, timeout=120)
                rows = parse_pdf_tables(local, cfg['cities'])
                print(f'  parsed rows: {len(rows)}')
                if rows:
                    print('  sample:')
                    for r in rows[:3]:
                        print(f"    {r['breed']} | {r['spec']} | {r['unit']} | {r['city']} = {r['price']}")
        except Exception as e:
            print(f'  ✗ {e}')


if __name__ == '__main__':
    main()

"""预览模式：不写入 ES / minio，仅打印将处理的内容"""
import argparse
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from sync import main as sync_main
from sync import fetch_all_periods, parse_detail_page, parse_pdf_tables, extract_period_from_title
from utils import load_config, fetch_html, download_file
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--period', default='', help='指定周期')
    parser.add_argument('--latest', action='store_true', help='只预览最新一期')
    args = parser.parse_args()

    cfg = load_config()
    items = fetch_all_periods(cfg)
    print(f'\n[preview] 共 {len(items)} 期')

    if args.period:
        items = [it for it in items if args.period in it['title']]
    if args.latest:
        items = items[:1]

    for it in items:
        print(f'\n── {it["title"]} ({it["publish_date"]}) ──')
        print(f'  detail: {it["detail_url"]}')
        try:
            html = fetch_html(it['detail_url'], timeout=cfg['site']['timeout_sec'])
            detail = parse_detail_page(html, cfg['site']['base_url'])
            print(f'  pdf: {detail["pdf_url"]}  ({detail["pdf_name"]})')
            period = extract_period_from_title(detail['title'] or it['title'])
            print(f'  period: {period}')

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

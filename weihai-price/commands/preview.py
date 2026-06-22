"""预览模式：不写入 ES / minio，仅打印将处理的内容"""
import argparse
import os
import sys
import tempfile
from datetime import datetime
from urllib.parse import urljoin

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from sync import (
    fetch_all_periods, _is_price_entry,
    parse_detail_page, parse_pdf_tables, extract_period_from_title,
)
from utils import load_config, fetch_html, download_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--period', default='', help='指定周期')
    parser.add_argument('--year', type=int, default=None, help='只预览指定年份（默认走 config.yml 的 default_year，0=不限制）')
    parser.add_argument('--latest', action='store_true', help='只预览最新一期')
    args = parser.parse_args()

    cfg = load_config()
    items = fetch_all_periods(cfg)
    print(f'\n[preview] 共 {len(items)} 条通知')

    if args.year is None:
        args.year = cfg.get('sync', {}).get('default_year', 0) or 0

    items = [it for it in items if _is_price_entry(it['title'])]
    if args.period:
        items = [it for it in items if args.period in it['title']]
    if args.year:
        items = [it for it in items if f'{args.year}年' in it['title']]
    if args.latest:
        items = items[:1]

    base_url = cfg['site']['base_url']
    print(f'[preview] 价目条目 {len(items)} 期 (year_filter={args.year})')

    for it in items:
        detail_url = urljoin(base_url, it['detail_url'])
        print(f'\n── {it["title"]} ({it["publish_date"]}) ──')
        print(f'  detail: {detail_url}')
        try:
            html = fetch_html(detail_url, headers={'User-Agent': cfg['site']['user_agent']},
                              timeout=cfg['site']['timeout_sec'])
            detail = parse_detail_page(html, base_url)
            print(f'  pdf: {detail["pdf_url"]}  ({detail["pdf_name"]})')
            period = extract_period_from_title(detail['title'] or it['title'])
            print(f'  period: {period}')

            with tempfile.TemporaryDirectory() as tmpdir:
                local = os.path.join(tmpdir, 's.pdf')
                download_file(detail['pdf_url'], local, referer=detail_url, timeout=120)
                rows = parse_pdf_tables(local, cfg.get('city', '威海'))
                print(f'  parsed rows: {len(rows)}')
                if rows:
                    print('  sample:')
                    for r in rows[:5]:
                        cat = r.get('category', '')
                        print(f"    [{cat}] {r['breed']} | {r['spec']} | {r['unit']} = {r['price']}")
                    # 按分类统计
                    cat_stats = {}
                    for r in rows:
                        c = r.get('category', '?')
                        cat_stats[c] = cat_stats.get(c, 0) + 1
                    print('  by category:')
                    for c, n in cat_stats.items():
                        print(f'    {c}: {n}')
        except Exception as e:
            print(f'  ✗ {e}')


if __name__ == '__main__':
    main()

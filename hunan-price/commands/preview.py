"""预览模式：不写入 ES / minio，仅打印将处理的内容"""
import argparse
import os
import sys
import tempfile
from collections import Counter

import pdfplumber

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from sync import (
    fetch_all_periods, fetch_detail_pdf,
    parse_half_month_table, parse_zixun_pdf,
)
from utils import load_config, download_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--period', default='', help='指定周期')
    parser.add_argument('--year', type=int, default=0, help='只预览指定年份的期')
    parser.add_argument('--latest', action='store_true', help='只预览最新一期')
    args = parser.parse_args()

    cfg = load_config()
    items = fetch_all_periods(cfg)
    keywords = cfg.get('journal_keywords', [])
    if keywords:
        items = [it for it in items if any(kw in it['title'] for kw in keywords)]
    print(f'\n[preview] 共 {len(items)} 条')

    if args.period:
        items = [it for it in items if args.period in it['title']]
    if args.year:
        items = [it for it in items if f'{args.year}年' in it['title']]
    if args.latest:
        items = items[:1]

    for it in items:
        print(f'\n── {it["title"]} ──')
        print(f'  detail: {it["detail_url"]}')
        try:
            title, pdf_url = fetch_detail_pdf(cfg, it['detail_url'])
            print(f'  pdf: {pdf_url}')
            if not pdf_url:
                continue
            with tempfile.TemporaryDirectory() as tmpdir:
                local = os.path.join(tmpdir, 's.pdf')
                download_file(pdf_url, local, timeout=600)
                if '行情资讯' in it['title']:
                    rows = parse_zixun_pdf(local, it['title'][:30])
                elif '行情表' in it['title']:
                    with pdfplumber.open(local) as pdf:
                        rows = parse_half_month_table(pdf.pages[0], it['title'][:30])
                else:
                    rows = []
                print(f'  parsed rows: {len(rows)}')
                if rows:
                    sec_counter = Counter(r['section'] for r in rows)
                    city_counter = Counter(r['city'] for r in rows)
                    period_sub_counter = Counter(r['period_sub'] for r in rows)
                    print(f'  by section: {dict(sec_counter)}')
                    print(f'  by city (TOP 15): {dict(city_counter.most_common(15))}')
                    print(f'  by period_sub (TOP 10): {dict(period_sub_counter.most_common(10))}')
                    print('  sample (前 5):')
                    for r in rows[:5]:
                        print(f"    {r['no']:5s} | {r['city']:10s} | {r['section'][:30]:30s} | "
                              f"{r['period_sub']:10s} | {r['breed'][:25]:25s} | "
                              f"{r['unit']:6s} = {r['price']} (rate {r['change_rate']}) (idx {r['index_value']})")
        except Exception as e:
            print(f'  ✗ {e}')


if __name__ == '__main__':
    main()
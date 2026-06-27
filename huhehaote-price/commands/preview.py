"""预览模式"""
import argparse
import os
import sys
import tempfile
from collections import Counter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from sync import fetch_all_periods, parse_pdf, fetch_detail_pdf
from utils import load_config, fetch_html, download_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--period', default='', help='指定周期')
    parser.add_argument('--year', type=int, default=0, help='只预览指定年份的期')
    parser.add_argument('--latest', action='store_true', help='只预览最新一期')
    args = parser.parse_args()

    cfg = load_config()
    items = fetch_all_periods(cfg)
    journal_kw = cfg.get('journal_keyword', '')
    if journal_kw:
        items = [it for it in items if journal_kw in it['title']]
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
            title, pdf_url, _ = fetch_detail_pdf(cfg, it['detail_url'])
            print(f'  pdf: {pdf_url}')
            if not pdf_url:
                continue
            with tempfile.TemporaryDirectory() as tmpdir:
                local = os.path.join(tmpdir, 's.pdf')
                download_file(pdf_url, local, timeout=600)
                rows = parse_pdf(local)
                print(f'  parsed rows: {len(rows)}')
                if rows:
                    cat_counter = Counter(r['category'] for r in rows)
                    city_counter = Counter(r['city'] for r in rows)
                    sec_counter = Counter(r['section'] for r in rows)
                    print(f'  by category: {dict(cat_counter)}')
                    print(f'  by city: {dict(city_counter)}')
                    print(f'  by section (TOP 10): {dict(sec_counter.most_common(10))}')
                    print('  sample (前 5):')
                    for r in rows[:5]:
                        print(f"    {r['no']:8s} | {r['city']:8s} | {r['section'][:18]:18s} | "
                              f"{r['breed'][:25]:25s} | {r['spec'][:25]:25s} | "
                              f"{r['unit']:6s} = {r['price']}  (含税 {r['tax_price']})")
        except Exception as e:
            print(f'  ✗ {e}')


if __name__ == '__main__':
    main()
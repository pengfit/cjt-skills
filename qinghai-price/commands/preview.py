"""预览模式：不写入 ES / minio，仅打印将处理的内容"""
import argparse
import os
import sys
import tempfile
from collections import Counter

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from sync import fetch_all_periods, parse_pdf, parse_list_page
from utils import load_config, fetch_html, download_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--period', default='', help='指定周期（title 模糊匹配）')
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
        print(f'  pdf: {it["pdf_url"]}')
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                local = os.path.join(tmpdir, 's.pdf')
                download_file(it['pdf_url'], local, timeout=600)
                rows = parse_pdf(local)
                print(f'  parsed rows: {len(rows)}')
                if rows:
                    sec_counter = Counter(r['section'] for r in rows)
                    print(f'  by section: {dict(sec_counter)}')
                    print('  sample (前 5):')
                    for r in rows[:5]:
                        print(f"    {r['no']:5s} | {r['section'][:18]:18s} | "
                              f"{r['breed'][:25]:25s} | {r['spec'][:30]:30s} | "
                              f"{r['unit']:6s} = {r['price']}  (含税 {r['tax_price']}) [{r.get('price_kind','')}]")
        except Exception as e:
            print(f'  ✗ {e}')


if __name__ == '__main__':
    main()
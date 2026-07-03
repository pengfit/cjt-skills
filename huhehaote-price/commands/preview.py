"""呼和浩特 - 预览模式（v0.8, 2026-07-03）

不写入 ES / minio，仅打印将处理的内容。
v0.8 改造：
  - 复用 sync.py 的工具函数（fetch_all_periods / fetch_detail_pdf / parse_pdf）
  - 复用 huhehaote_collector.parse_period_window 展示 period 窗口字段
  - 复用 journal_keyword 过滤
"""
import argparse
import os
import sys
import tempfile
from collections import Counter
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from sync import (
    fetch_all_periods, fetch_detail_pdf, parse_pdf,
)
from huhehaote_collector import parse_period_window
from utils import load_config, fetch_html, download_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--period', default='', help='指定周期')
    parser.add_argument('--year', type=int, default=datetime.now().year, help='只预览指定年份的期（默认本年，0=不限制）')
    parser.add_argument('--latest', action='store_true', help='只预览最新一期')
    args = parser.parse_args()

    cfg = load_config()
    journal_kw = cfg.get('journal_keyword', '信息价')

    items = fetch_all_periods(cfg)
    print(f'\n[preview] 共 {len(items)} 期 (journal_keyword="{journal_kw}")')

    # 过滤
    if args.period:
        items = [it for it in items if args.period in it['title']]
    if journal_kw:
        items = [it for it in items if journal_kw in it['title']]
    if args.year:
        items = [it for it in items if f'{args.year}年' in it['title']]
    if args.latest:
        items = items[:1]

    print(f'[preview] 过滤后 {len(items)} 期')

    for it in items:
        print(f'\n── {it["title"]} ({it["publish_date"]}) ──')
        print(f'  detail: {it["detail_url"]}')
        try:
            title, pdf_url, pdf_link_text = fetch_detail_pdf(cfg, it['detail_url'])
            print(f'  pdf: {pdf_url}  ({pdf_link_text})')

            # v0.8 字段：period 窗口
            win = parse_period_window(title or it['title'])
            print(
                f'  period: {win["period"]}  '
                f'start: {win["period_start"]}  '
                f'end: {win["period_end"]}  '
                f'days: {win["period_days"]}'
            )

            if not pdf_url:
                print(f'  [skip] 无 PDF 链接')
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
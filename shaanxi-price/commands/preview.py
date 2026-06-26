"""陕西工程造价材料信息 - 预览模式（不写 ES、不传 MinIO）

用法：
    python3 preview.py                          # 预览最新一期
    python3 preview.py --period 2026.5期        # 预览指定期
    python3 preview.py --year 2026 --limit 3    # 预览最近 3 期
"""
import argparse
import os
import sys
import tempfile
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import (
    load_config, fetch_html, download_file,
    parse_list_page, parse_detail_page,
    extract_period_from_title, extract_city_from_title,
)
from pdf_parser import parse_pdf_pages
from sync import fetch_all_periods


def main():
    parser = argparse.ArgumentParser(description='陕西工程造价材料信息预览')
    parser.add_argument('--period', default='', help='指定 period')
    parser.add_argument('--year', type=int, default=0, help='年份（默认 config.sync.target_year）')
    parser.add_argument('--limit', type=int, default=3, help='最多预览 N 期')
    parser.add_argument('--city', default='', help='只预览指定 city')
    parser.add_argument('--show-pages', type=int, default=3, help='每个 PDF 显示前 N 页样本')
    args = parser.parse_args()

    cfg = load_config()

    if args.year == 0:
        args.year = cfg.get('sync', {}).get('target_year', datetime.now().year)

    print(f'[preview] year={args.year}, period={args.period!r}, limit={args.limit}')

    items = fetch_all_periods(cfg)

    # 过滤
    todo = []
    for it in items:
        if args.year and f'{args.year}年' not in it['title']:
            continue
        if args.period and args.period not in it['title']:
            continue
        todo.append(it)
    todo = todo[:args.limit]

    print(f'[preview] 共 {len(todo)} 期待预览\n')

    headers = {
        'User-Agent': cfg['site']['user_agent'],
        'Referer': cfg['site'].get('referer', cfg['site']['base_url']),
    }

    for idx, item in enumerate(todo, 1):
        print(f'=== [{idx}/{len(todo)}] {item["title"]} ===')
        print(f'  publish_date: {item["publish_date"]}')
        print(f'  detail_url: {item["detail_url"]}')

        try:
            detail_html = fetch_html(item['detail_url'], headers=headers, timeout=cfg['site']['timeout_sec'])
            detail = parse_detail_page(detail_html, item['detail_url'])
            if not detail['pdf_url']:
                print('  ✗ 未找到 PDF 链接')
                continue
            print(f'  pdf_url: {detail["pdf_url"]}')
            print(f'  pdf_name: {detail["pdf_name"]}')

            period = extract_period_from_title(detail['title'] or item['title'])
            city = extract_city_from_title(item['title'], cfg['city_patterns'], cfg['province_label'])
            print(f'  period: {period}, city: {city}')

            if args.city and args.city != city:
                print(f'  --skip (city={city} != {args.city})')
                continue

            with tempfile.TemporaryDirectory() as tmpdir:
                local_pdf = os.path.join(tmpdir, 'source.pdf')
                download_file(detail['pdf_url'], local_pdf, headers=headers, timeout=180)

                page_results = parse_pdf_pages(local_pdf, city)
                total_rows = sum(len(rows) for _, _, rows in page_results)
                pages_with_data = sum(1 for _, pt, rows in page_results if rows and not pt.startswith('error'))
                type_counts = {}
                for _, pt, rows in page_results:
                    if rows:
                        type_counts[pt] = type_counts.get(pt, 0) + len(rows)
                print(f'  parsed: {pages_with_data} pages with data, {total_rows} rows total')
                print(f'  type breakdown: {type_counts}')

                # Show sample rows
                samples = []
                for _, pt, rows in page_results:
                    for r in rows:
                        if r.price is not None or r.tax_price is not None:
                            samples.append((pt, r))
                for pt, r in samples[:8]:
                    county = r.county or ''
                    print(f'    [{pt}] code={r.code} | {r.breed[:18]:18} | {r.spec[:25]:25} | unit={r.unit:5} | county={county:10} | price={r.price} | tax={r.tax_price}')
                if len(samples) > 8:
                    print(f'    ...({len(samples) - 8} more)')

        except Exception as e:
            print(f'  ✗ 失败: {e}')
        print()


if __name__ == '__main__':
    main()

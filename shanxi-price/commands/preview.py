"""山西 · 预览模式：不写入 ES / MinIO, 仅打印将处理的内容。"""
import argparse
import os
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from sync import (
    fetch_all_periods, parse_pdf_tables, parse_period_from_title,
    should_include,
)
from utils import load_config, download_file


def main():
    parser = argparse.ArgumentParser(description='山西工程造价材料信息预览')
    parser.add_argument('--period', default='', help='指定 period（如 2026.3-4月）')
    parser.add_argument('--year', type=int, default=None,
                        help='只预览指定年份（默认 cfg.sync.default_year=2026；0=不限制）')
    parser.add_argument('--latest', action='store_true', help='只预览最新一期')
    parser.add_argument('--limit', type=int, default=0, help='最多预览 N 期（0=全部）')
    parser.add_argument('--no-filter', action='store_true',
                        help='不过滤（显示全部 180 条）')
    args = parser.parse_args()

    cfg = load_config()
    items = fetch_all_periods(cfg)
    print(f'\n[preview] 共 {len(items)} 条（所有页合计）')

    if not args.no_filter:
        if args.year is None:
            args.year = cfg.get('sync', {}).get('default_year', 0)
        if args.period:
            items = [it for it in items if args.period in it['title']]
        if args.year:
            items = [it for it in items if f'{args.year}' in it['title']]
        # include/exclude 关键词过滤
        filtered = []
        excluded_samples = []
        for it in items:
            include, reason = should_include(it, cfg)
            if include:
                filtered.append(it)
            else:
                excluded_samples.append((it['title'], reason))
        print(f'[preview] 过滤后 {len(filtered)} 条（排除 {len(excluded_samples)} 条）')
        if excluded_samples[:5]:
            print('[preview] 排除样例:')
            for t, r in excluded_samples[:5]:
                print(f'  ✗ {t[:60]}... → {r}')
        items = filtered
    else:
        items = list(items)

    if args.latest:
        items = items[:1]
    if args.limit > 0:
        items = items[:args.limit]

    print(f'[preview] 实际预览 {len(items)} 期\n')

    for it in items:
        print(f'── {it["title"]} ({it["publish_date"]}, 第{it["page"]+1}页) ──')
        print(f'  detail: {it["detail_url"]}')
        win = parse_period_from_title(it['title'])
        if win and not win.get('invalid'):
            print(
                f'  period: {win["period"]}  '
                f'start: {win["period_start"]}  '
                f'end: {win["period_end"]}  '
                f'days: {win["period_days"]}'
            )
        else:
            print(f'  period: <无法解析>')


if __name__ == '__main__':
    main()
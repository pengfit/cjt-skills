#!/usr/bin/env python3
"""预览模式"""
import sys, os, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import warnings
warnings.filterwarnings('ignore')
from commands.utils import SiteSession, parse_page, AREA_CODES, get_latest_period, get_all_periods

parser = argparse.ArgumentParser()
parser.add_argument('--pages', type=int, default=2)
parser.add_argument('--period', default='', help='指定周期，如 2026年03月（默认最新）')
parser.add_argument('--area', default='', help='指定地区代码，如 川A')
args = parser.parse_args()

# 解析周期
if args.period:
    periods = get_all_periods()
    period_map = {p['PeriodName']: p['Guid'] for p in periods}
    period_guid = period_map.get(args.period, '')
    if not period_guid:
        print(f"[!] 未找到周期 {args.period}，使用最新周期")
        _, period_guid = get_latest_period()
        period_name = args.period
    else:
        period_name = args.period
else:
    period_name, period_guid = get_latest_period()

print(f"[i] 周期: {period_name}")

session = SiteSession()
areas = [args.area] if args.area else sorted(AREA_CODES.keys())

for area in areas:
    html, _, period = session.fetch(area, period_guid, 1)
    if not html:
        print(f"{area}: 抓取失败")
        continue
    city_headers, rows, total, page_size, _ = parse_page(html)
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1
    print(f"\n=== {AREA_CODES.get(area, area)} ({area}) {period} ===")
    print(f"总记录: {total}, 总页数: {total_pages}, 城市列: {len(city_headers)}")
    print(f"城市: {', '.join(city_headers[:6])}...")
    print(f"前 {min(args.pages, total_pages)} 页预览:")
    for page in range(1, min(args.pages + 1, total_pages + 1)):
        if page > 1:
            html, _, _ = session.fetch(area, period_guid, page)
            city_headers, rows, _, _, _ = parse_page(html)
        print(f"\n  -- 第 {page} 页 --")
        for row in rows[:4]:
            print(f"    {row.get('breed')} | {row.get('spec')} | {row.get('unit')} | {row.get('price')}")

#!/usr/bin/env python3
"""预览：抓最新 1 个月的数据，解析 + 清洗后打印（不写 ES）。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

import utils as _u


def main():
    cfg = _u.load_config()
    print(f"=== 预览（吉林 · 不写入 ES） ===\n")

    s = requests.Session()
    s.get(
        cfg['site']['base_url'] + f"?city={cfg['site']['city_id']}",
        headers=_u.DEFAULT_HEADERS,
        timeout=15,
    )

    from datetime import datetime
    last_m = datetime.now().month
    year = cfg['sync']['year']

    for m in range(1, last_m + 1):
        period = f"{year}年{m}月份"
        try:
            html = _u.fetch_list_page(
                s,
                base_url=cfg['site']['base_url'],
                city_id=cfg['site']['city_id'],
                price_time=period,
                page=1,
                max_retries=2,
            )
        except Exception as e:
            print(f"  {period} ✗ {e}")
            continue

        rows = _u.parse_rows(html)
        print(f"\n--- {period} (page=1, {len(rows)} 条) ---")
        for r in rows[:5]:
            print(f"  {r['county']:<6s} | {r['breed']:<20s} | {r['spec']:<15s} | "
                  f"{r['price']:>8} / {r['tax_price']:>8} {r['unit']}")
        if len(rows) > 5:
            print(f"  ... 还有 {len(rows) - 5} 条")


if __name__ == "__main__":
    main()
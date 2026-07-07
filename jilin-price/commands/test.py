#!/usr/bin/env python3
"""连通性测试：ES + 源站。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

import utils as _u


def main():
    cfg = _u.load_config()

    # 1. ES 连通性
    print("=== ES 连通性 ===")
    try:
        r = requests.get(cfg["es"]["host"], timeout=10)
        print(f"  {cfg['es']['host']} → {r.status_code}")
        r2 = requests.head(f"{cfg['es']['host']}/{cfg['es']['index']}", timeout=10)
        print(f"  {cfg['es']['index']} → {r2.status_code} {'存在' if r2.status_code==200 else '不存在'}")
    except Exception as e:
        print(f"  ✗ ES 失败: {e}")

    # 2. 源站连通性
    print("\n=== 源站连通性 ===")
    s = requests.Session()
    try:
        r = s.get(
            cfg["site"]["base_url"] + f"?city={cfg['site']['city_id']}",
            headers=_u.DEFAULT_HEADERS,
            timeout=15,
        )
        print(f"  首页 GET → {r.status_code}")
        # 测试 2026年7月份
        html = _u.fetch_list_page(
            s,
            base_url=cfg["site"]["base_url"],
            city_id=cfg["site"]["city_id"],
            price_time="2026年7月份",
            page=1,
        )
        rows = _u.parse_rows(html)
        print(f"  2026年7月份 抓取 → {len(rows)} 条")
        if rows:
            r0 = rows[0]
            print(f"    示例: county={r0['county']} | breed_raw='{r0['breed_raw']}' → breed='{r0['breed']}' | spec='{r0['spec']}' | price={r0['price']} tax={r0['tax_price']}")
    except Exception as e:
        print(f"  ✗ 源站失败: {e}")


if __name__ == "__main__":
    main()
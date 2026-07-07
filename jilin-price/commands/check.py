#!/usr/bin/env python3
"""增量检测：扫描源站 + 比对 ES + 本地进度，输出待同步清单（不写 ES）。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

import utils as _u


def main():
    cfg = _u.load_config()

    print(f"=== 增量检测（吉林 · {cfg['sync']['year']} 年） ===\n")

    # 1. 对每个月做一次轻量查询（page=1），看是否有数据
    from datetime import datetime
    last_m = datetime.now().month
    year = cfg['sync']['year']
    s = requests.Session()
    # 先 GET 首页拿 session
    s.get(
        cfg['site']['base_url'] + f"?city={cfg['site']['city_id']}",
        headers=_u.DEFAULT_HEADERS,
        timeout=15,
    )

    todo = []
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
            rows = _u.parse_rows(html)
            print(f"  {period:<12s} {len(rows):>4d} 条（page=1）")
            if rows:
                todo.append(period)
        except Exception as e:
            print(f"  {period:<12s} ✗ 抓取失败: {e}")

    print(f"\n待同步月份: {len(todo)} 个")
    if todo:
        for p in todo:
            print(f"  - {p}")
        print(f"\n运行 './run.sh sync' 开始同步")


if __name__ == "__main__":
    main()
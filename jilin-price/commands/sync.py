#!/usr/bin/env python3
"""吉林 sync 入口（v0.1, 2026-07-07）

默认走 JilinCollector（SyncRunner 化）。
仅同步 2026 年数据（道友要求）。

用法:
  ./run.sh sync                          # 全年（到当前月）
  ./run.sh sync --year 2026 --max-month 7
  ./run.sh sync --reset                  # 重置进度
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from datetime import datetime

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="吉林工程造价材料信息同步")
    parser.add_argument("--year", type=int, default=2026, help="抓取年份（默认 2026）")
    parser.add_argument("--max-month", type=int, default=0,
                        help="最大月份（0=当前月），如 7 表示只跑到 7 月")
    parser.add_argument("--diqu", default="", help="地区筛选（默认空 = 吉林市整体）")
    parser.add_argument("--reset", action="store_true", help="重置本地进度")
    parser.add_argument("--run-id", default="", help="指定 run_id")
    parser.add_argument("--max-units", type=int, default=None, help="最多处理几个工作单元")
    args = parser.parse_args()

    from commands.jilin_collector import make_collector

    cfg_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config.yml",
    )
    run_id = args.run_id or f"jl_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    print(f"[JilinCollector 路径] 启动")
    print(f"  year={args.year}  max_month={args.max_month or 'now'}")
    print(f"  diqu={args.diqu or '(全部/吉林市整体)'}")
    print(f"  run_id={run_id}")

    collector = make_collector(
        cfg_path=cfg_path,
        run_id=run_id,
        year=args.year,
        diqu=args.diqu,
        max_month=args.max_month,
    )
    result = collector.run(reset=args.reset, max_units=args.max_units)
    print(f"\n[JilinCollector 路径] 完成: {result}")
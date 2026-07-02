#!/usr/bin/env python3
"""同步入口 - 默认走 chongqing_collector（v0.8 SyncRunner 基类化版本）

v0.9 (2026-07-02) ：chongqing_collector 切为默认路径
  - 默认走 ChongqingCollector（v0.8 SyncRunner 试点已生产验证 1 次，run_id=v08_pilot_full_*）
  - --legacy 走原 v3 cmd_sync（逃生通道，不推荐）
  - --max-units 只在 collector 路径生效（验证用）
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="重庆工程造价材料信息同步（默认 Collector 路径）")
    parser.add_argument("--reset", action="store_true", help="重置进度，重新开始")
    parser.add_argument("--period", default="2026年01月", help="目标周期（兼容旧参数，等价 --periods 单值）")
    parser.add_argument("--periods", default="",
                        help="多周期，逗号分隔，如 '2026年01月,2026年02月,2026年03月,2026年04月,2026年05月'")
    parser.add_argument("--run-id", default="", help="指定 run_id")
    parser.add_argument("--tab-id", default="", help="浏览器标签页 ID（必填）")
    parser.add_argument("--source", default="all",
                        help="数据来源: district / mortar / citywide / all")
    parser.add_argument("--legacy", action="store_true",
                        help="v3 兼容：走原 cmd_sync（旧生产路径）。**默认走 Collector**。仅在 Collector 异常时备用。")
    parser.add_argument("--max-units", type=int, default=None,
                        help="Collector 路径：只跑前 N 个工作单元（验证用），不传则跑全部")
    args = parser.parse_args()

    if args.legacy:
        # v3 兼容路径：原 cmd_sync（生产备援）
        from commands.write_es import cmd_sync
        print(f"[v3 兼容路径] cmd_sync 启动")
        print(f"  tab_id={args.tab_id}, period={args.period}, source={args.source}")
        cmd_sync(args)
    else:
        # 默认路径：ChongqingCollector（v0.8 SyncRunner 抽象基类）
        # 已在 2026-07-02 生产试跑 1 次（run_id=v08_pilot_full_20260702，5 个月全量）
        from commands.chongqing_collector import make_collector
        from datetime import datetime
        cfg_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'config.yml',
        )
        # 解析 periods
        if args.periods:
            periods = [p.strip() for p in args.periods.split(',') if p.strip()]
        else:
            periods = [args.period]
        # 解析 sources
        sources = ['district', 'mortar', 'citywide'] if args.source == 'all' else [args.source]
        run_id = args.run_id or f"cq_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        print(f"[Collector 路径] ChongqingCollector 启动")
        print(f"  tab_id={args.tab_id}, periods={periods}, sources={sources}")
        collector = make_collector(cfg_path, args.tab_id, periods, run_id, sources=sources)
        result = collector.run(reset=args.reset, max_units=args.max_units)
        print(f"\n[Collector 路径] 完成: {result}")
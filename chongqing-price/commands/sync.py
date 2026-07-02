#!/usr/bin/env python3
"""同步入口 - 转发给 write_es.py sync 命令（或 chongqing_collector 试点）

v0.8 (2026-07-02) ：加 --use-collector flag 启用 SyncRunner 试点版本
  - 默认走原 cmd_sync（生产安全）
  - --use-collector 走 ChongqingCollector（v0.8 实验性，未生产验证）
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 复用 gov_price_etl 通用层（v0.7 P1 抽取后）
from commands.write_es import cmd_sync
import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="重庆工程造价材料信息同步")
    parser.add_argument("--reset", action="store_true", help="重置进度，重新开始")
    parser.add_argument("--period", default="2026年01月", help="目标周期（兼容旧参数，等价 --periods 单值）")
    parser.add_argument("--periods", default="",
                        help="多周期，逗号分隔，如 '2026年01月,2026年02月,2026年03月,2026年04月,2026年05月'")
    parser.add_argument("--run-id", default="", help="指定 run_id")
    parser.add_argument("--tab-id", default="", help="浏览器标签页 ID")
    parser.add_argument("--source", default="all",
                        help="数据来源: district / mortar / citywide / all")
    parser.add_argument("--use-collector", action="store_true",
                        help="v0.8 实验性：使用 chongqing_collector.ChongqingCollector 试点版本"
                             "（SyncRunner 抽象基类）。**未生产验证**，请谨慎使用。")
    args = parser.parse_args()

    if args.use_collector:
        # v0.8 试点：ChongqingCollector 走 SyncRunner 主流程
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

        print(f"[v0.8 试点] ChongqingCollector 启动")
        print(f"  tab_id={args.tab_id}, periods={periods}, sources={sources}")
        collector = make_collector(cfg_path, args.tab_id, periods, run_id)
        result = collector.run(reset=args.reset)
        print(f"\n[v0.8 试点] 完成: {result}")
    else:
        # 生产路径：原 cmd_sync（v3 完整版）
        cmd_sync(args)
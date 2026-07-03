#!/usr/bin/env python3
"""同步入口 - 默认走 hainan_collector（v0.8 SyncRunner 基类化版本，参照重庆）

v0.8 (2026-07-02) ：hainan_collector 切为默认路径
  - 默认走 HainanCollector（SyncRunner 抽象基类化）
  - 复用旧 sync.py 的纯函数（parse_pdf / fetch_all_periods / parse_list_page /
    parse_detail_page / extract_period_from_title / bulk_index / _doc_id）
  - 进度文件 .hainan_sync_progress.json 结构保留（{'done': {detail_url: {...}}}）
    以兼容之前的本地状态

参照实现：chongqing-price/commands/chongqing_collector.py + sync.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from datetime import datetime

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="海南工程造价材料信息同步（默认 Collector 路径，参照重庆）")
    parser.add_argument("--period", default="", help="指定周期（substring 匹配 title）")
    parser.add_argument("--year", type=int, default=0, help="只入库指定年份的期（默认 0=不限制）")
    parser.add_argument("--exclude-period", default="", help="排除指定周期（substring 匹配）")
    parser.add_argument("--all", action="store_true", help="同步所有未入仓的期")
    parser.add_argument("--latest", action="store_true", help="只同步最新一期")
    parser.add_argument("--reset", action="store_true", help="重置本地进度，重新开始")
    parser.add_argument("--dry-run", action="store_true", help="预览，不写入 ES/minio（解析 PDF 仍跑）")
    parser.add_argument("--max-units", type=int, default=None,
                        help="Collector 路径：只跑前 N 个工作单元（验证用）")
    args = parser.parse_args()

    # 默认走 HainanCollector 路径
    from commands.hainan_collector import make_collector
    from commands.utils import load_config

    cfg = load_config()
    run_id = f"hn_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    print(f"[Collector 路径] HainanCollector 启动")
    print(f"  year={args.year or '-'}, exclude_period={args.exclude_period or '-'}, "
          f"period={args.period or '-'}, latest={args.latest}, dry_run={args.dry_run}")

    collector = make_collector(
        cfg=cfg,
        run_id=run_id,
        year=args.year,
        exclude_period=args.exclude_period,
        dry_run=args.dry_run,
    )

    # --latest / --period 处理：在 SyncRunner.run() 之前包一层 _list_work_units
    if args.latest:
        all_units = collector._list_work_units()
        if not all_units:
            print("[hainan] 无新数据")
            sys.exit(0)
        first = all_units[0]
        collector._list_work_units = lambda: [first]
    elif args.period:
        old_list = collector._list_work_units
        collector._list_work_units = lambda: [
            u for u in old_list() if args.period in u["title"]
        ]

    result = collector.run(reset=args.reset, max_units=args.max_units)

    # 汇总
    print()
    print("=" * 60)
    print(f"[hainan] 总单元: {result['total']}")
    print(f"[hainan] 完成:   {result['done']}")
    print(f"[hainan] 失败:   {result['failed']}")
    print(f"[hainan] 跳过:   {result['skipped']}")
    print(f"[hainan] 写入:   {result['docs_written']} 条")
    print(f"[hainan] 耗时:   {result['duration_sec']:.1f}s")
    if result["interrupted"]:
        print("[hainan] ⚠️  被 SIGINT 中断（已保留进度）")

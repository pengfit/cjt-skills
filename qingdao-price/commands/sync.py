#!/usr/bin/env python3
"""青岛工程造价材料信息 - 同步入口（v0.9, 2026-07-03）

默认走 qingdao_collector（v0.9 SyncRunner 抽象基类化版本），参考 chongqing_collector.py。

CLI 兼容 v0.8：
    python3 commands/sync.py [--year 2026] [--period 2026.5月] [--latest] [--all]
                              [--reset] [--dry-run]

v0.9 新增：
    --run-id   指定 run_id（默认 qd_run_YYYYMMDD_HHMMSS）
    --max-units 只跑前 N 个工作单元（验证用）
"""
import argparse
import os
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.dirname(SCRIPT_DIR))


def main():
    parser = argparse.ArgumentParser(description="青岛工程造价材料信息同步（默认 Collector 路径）")
    parser.add_argument("--period", default="", help="指定周期（兼容 v0.8 单周期过滤）")
    parser.add_argument("--year", type=int, default=None,
                        help="只入库指定年份（默认走 config.yml 的 default_year，0=不限制）")
    parser.add_argument("--all", action="store_true", help="同步所有未入仓的期（v0.8 兼容）")
    parser.add_argument("--reset", action="store_true", help="重置本地进度，从头开始")
    parser.add_argument("--dry-run", action="store_true", help="预览，不写入 ES / MinIO")
    parser.add_argument("--latest", action="store_true", help="只同步最新一期")
    parser.add_argument("--run-id", default="", help="指定 run_id")
    parser.add_argument("--max-units", type=int, default=None,
                        help="Collector 路径：只跑前 N 个工作单元（验证用）")
    parser.add_argument("--legacy", action="store_true",
                        help="v0.8 兼容：走旧 sync.py（仅在 Collector 异常时备用）")
    args = parser.parse_args()

    run_id = args.run_id or f"qd_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    year = args.year if args.year is not None else 0

    print(f"[Collector 路径] QingdaoCollector 启动（v0.9, 2026-07-03）")
    print(f"  run_id={run_id}  year={year or '(无限制)'}  dry_run={args.dry_run}  reset={args.reset}")

    if args.legacy:
        print("[legacy 路径] 走 v0.8 sync.py（逃生通道）")
        from sync_legacy import main as legacy_main
        legacy_main()
        return

    from qingdao_collector import make_collector

    cfg_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config.yml",
    )
    collector = make_collector(
        cfg_path=cfg_path,
        run_id=run_id,
        year=year,
        dry_run=args.dry_run,
    )

    # --period 兼容：先在 cfg 里把对应期放到 work unit 之前
    # SyncRunner 的 _list_work_units 已经按 year 过滤；如果指定 --period，
    # 在 _on_unit_start 里再过滤（轻量级 filter hook）
    if args.period:
        # 用 max_units 思路：在 _list_work_units 返回的 list 上做截取
        original_list = collector._list_work_units
        def filtered_list():
            units = original_list()
            units = [u for u in units if args.period in u.get("period", "")]
            if args.latest:
                units = units[:1]
            return units
        collector._list_work_units = filtered_list
    elif args.latest:
        original_list = collector._list_work_units
        def take_latest():
            return original_list()[:1]
        collector._list_work_units = take_latest

    result = collector.run(reset=args.reset, max_units=args.max_units)
    print(f"\n[Collector 路径] 完成: {result}")

    # 失败总结
    if result["failed"] > 0:
        print(f"⚠️  {result['failed']} 期失败，详见 .qingdao_sync_progress.json")


if __name__ == "__main__":
    main()

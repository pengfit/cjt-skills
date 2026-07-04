#!/usr/bin/env python3
"""陕西工程造价材料信息 - 同步入口（v1.0, 2026-07-03）

v1.0 重构：默认走 shaanxi_collector（SyncRunner 抽象基类化），参考 chongqing_collector
和 qingdao_collector 的模式。

CLI 兼容 v0.5：
    python3 commands/sync.py [--year 2026] [--period 2026.5月] [--latest] [--all]
                              [--reset] [--dry-run]

v1.0 新增：
    --run-id     指定 run_id（默认 sn_run_YYYYMMDD_HHMMSS）
    --max-units  只跑前 N 个工作单元（验证用）
    --legacy     走 sync_legacy.py（逃生通道，仅在 Collector 异常时备用）

数据范围：默认 cfg.sync.target_year = 2026。

必含字段：每条 doc 含 period_start / period_end / period_days（道友硬要求）。
"""
import argparse
import os
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.dirname(SCRIPT_DIR))


# ── 兼容旧 import path（让 check.py / preview.py / status.py 仍可 from sync import ...） ──
# 新 collector 走 ShaanxiCollector（主流程），但 fetch_all_periods / PROGRESS_FILE / load_progress
# 这几个工具函数依然从 sync_legacy 透传（站点列表解析逻辑无变化）。
from sync_legacy import (  # noqa: E402
    fetch_all_periods,
    PROGRESS_FILE,
    load_progress,
    save_progress,
    bulk_index,
    row_to_doc,
)


def main():
    parser = argparse.ArgumentParser(
        description="陕西工程造价材料信息同步（v1.0 默认 Collector 路径）"
    )
    # v0.5 兼容参数
    parser.add_argument("--period", default="", help="指定 period（如 '2026.5月' / '2026.5期'）")
    parser.add_argument("--year", type=int, default=None,
                        help="只入库指定年份（默认 cfg.sync.target_year=2026）")
    parser.add_argument("--all", action="store_true", help="同步所有未入仓的期（v0.5 兼容）")
    parser.add_argument("--reset", action="store_true", help="重置本地进度，从头开始")
    parser.add_argument("--dry-run", action="store_true", help="预览，不写入 ES / MinIO")
    parser.add_argument("--latest", action="store_true", help="只同步最新一期")
    parser.add_argument("--limit", type=int, default=0, help="最多同步 N 期（0=全部，兼容 v0.5）")
    # v1.0 新增参数
    parser.add_argument("--run-id", default="", help="指定 run_id（默认 sn_run_YYYYMMDD_HHMMSS）")
    parser.add_argument("--max-units", type=int, default=None,
                        help="Collector 路径：只跑前 N 个工作单元（验证用）")
    parser.add_argument("--legacy", action="store_true",
                        help="v0.5 兼容：走 sync_legacy.py（旧生产路径）。**默认走 Collector**。"
                             "仅在 Collector 异常时备用。")
    args = parser.parse_args()

    if args.legacy:
        # v0.5 兼容路径：旧 sync.py（生产备援）
        print(f"[v0.5 兼容路径] sync_legacy 启动")
        print(f"  period={args.period}, year={args.year}, latest={args.latest}")
        from sync_legacy import main as legacy_main
        legacy_main()
        return

    # 默认 Collector 路径
    from shaanxi_collector import make_collector

    cfg_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config.yml",
    )
    year = args.year if args.year is not None else 0
    run_id = args.run_id or f"sn_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    print(f"[Collector 路径] ShaanxiCollector 启动（v1.0, 2026-07-03）")
    print(f"  run_id={run_id}  year={year or '(cfg.sync.target_year)'}  "
          f"dry_run={args.dry_run}  reset={args.reset}")
    print(f"  必含字段：period_start / period_end / period_days")

    collector = make_collector(
        cfg_path=cfg_path,
        run_id=run_id,
        year=year,
        dry_run=args.dry_run,
    )

    # --period / --latest 兼容：在 _list_work_units 返回值上做轻量级 filter hook
    if args.period or args.latest or args.limit:
        original_list = collector._list_work_units

        def filtered_list():
            units = original_list()
            if args.period:
                units = [u for u in units if args.period in u.get("period", "")]
            if args.latest:
                units = units[:1]
            if args.limit and len(units) > args.limit:
                units = units[:args.limit]
            return units

        collector._list_work_units = filtered_list

    result = collector.run(reset=args.reset, max_units=args.max_units)
    print(f"\n[Collector 路径] 完成: {result}")

    if result["failed"] > 0:
        print(f"⚠️  {result['failed']} 期失败，详见 .shaanxi_sync_progress.json")


if __name__ == "__main__":
    main()
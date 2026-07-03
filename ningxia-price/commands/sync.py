"""宁夏工程造价信息 - 同步入口（v0.8, 2026-07-03）

默认走 ningxia_collector.py（SyncRunner 抽象基类化版本）。
--legacy 走 v3 cmd_legacy_sync（逃生通道，保留旧字段写入）。

v0.8 字段扩展（道友要求，缺一不可）：
  period / period_start / period_end / period_days
  - 双月刊：第 N 期 → 覆盖 (N-1)*2+1 月 至 N*2 月
    例：第2期 → 2026-03-01 ~ 2026-04-30（61 天）

用法：
  python3 commands/sync.py --year 2026                  # 默认走 collector
  python3 commands/sync.py --year 2026 --legacy         # 走 v3 旧路径
  python3 commands/sync.py --year 2026 --reset          # 重置本地进度
  python3 commands/sync.py --year 2026 --max-units 1    # 测试跑 1 期
  python3 commands/sync.py --year 2026 --period "2026年第2期"   # 限定单期
  python3 commands/sync.py --year 2026 --dry-run        # 只解析不入库
"""
import argparse
import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)


def main():
    parser = argparse.ArgumentParser(description='宁夏工程造价同步（v0.8 SyncRunner）')
    parser.add_argument('--year', type=int, default=2026, help='同步年份（默认 2026）')
    parser.add_argument('--period', default='', help='限定周期（标题含此串），如 "2026年第2期"')
    parser.add_argument('--exclude-period', default='', help='排除周期')
    parser.add_argument('--all', action='store_true', help='同步所有未入仓的期（不限于指定年份）')
    parser.add_argument('--reset', action='store_true', help='重置本地进度')
    parser.add_argument('--dry-run', action='store_true', help='只解析不入库')
    parser.add_argument('--latest', action='store_true', help='只同步最新一期')
    parser.add_argument('--max-units', type=int, default=0, help='最多处理多少期（测试用，0=全部）')
    parser.add_argument('--legacy', action='store_true', help='走 v3 旧路径（逃生通道）')
    parser.add_argument('--run-id', default='', help='本次运行标识（默认自动生成）')
    args = parser.parse_args()

    if args.legacy:
        # v3 旧路径（保留原 sync.py 主流程，但已迁移到独立函数 cmd_legacy_sync）
        from sync_v3_legacy import cmd_legacy_sync
        cmd_legacy_sync(args)
        return

    # 默认走 collector
    from ningxia_collector import make_collector
    import time

    run_id = args.run_id or f"v08_{time.strftime('%Y%m%d_%H%M%S')}"
    print(f'[ningxia] run_id={run_id}')

    collector = make_collector(
        cfg_path=os.path.join(os.path.dirname(SCRIPT_DIR), 'config.yml'),
        year=args.year,
        run_id=run_id,
    )

    # 解析器（apply CLI filters via subclass override if needed）
    if args.period or args.exclude_period or args.latest:
        # 包装一层过滤（不影响基类）
        import ningxia_collector as nc
        orig_list = collector._list_work_units

        def filtered_list():
            units = orig_list()
            if args.period:
                units = [u for u in units if args.period in u['period']]
            if args.exclude_period:
                units = [u for u in units if args.exclude_period not in u['period']]
            if args.latest:
                units = units[-1:] if units else []
            return units

        collector._list_work_units = filtered_list

    if args.dry_run:
        # dry-run：不写 ES，只打印
        units = collector._list_work_units()
        print(f'[dry-run] 共 {len(units)} 个工作单元')
        for u in units:
            print(f'  {u["period"]:14s} {u["title"][:50]}  {u["period_start"]} ~ {u["period_end"]} ({u["period_days"]}d)')
        return

    summary = collector.run(
        max_units=args.max_units if args.max_units else None,
        reset=args.reset,
    )
    print(f'\n[ningxia] 全部完成:')
    for k, v in summary.items():
        print(f'  {k}: {v}')


if __name__ == '__main__':
    main()

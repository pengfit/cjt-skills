#!/usr/bin/env python3
"""sync.py - 日照工程造价信息同步入口（v1.1 多期 + API 模式, 2026-07-03）

v1.1 (2026-07-03)：
  - 反编译源站 SPA axios 调用 → fetch_data.py 走 Playwright + 内部 fetch
  - 支持多期回溯（periods 参数）：'2026-01' ~ '2026-05' 一次性拉全
  - 默认走 RizhaoCollector（v1.0 SyncRunner 抽象基类）
  - --legacy 走 v0 流式旧路径

CLI 入口示例：
    python3 commands/sync.py                                  # 默认 3 tab + 当前期
    python3 commands/sync.py --periods 2026-01,2026-02,2026-03  # 3 个月 × 3 tab = 9 units
    python3 commands/sync.py --periods 2026-01..2026-05      # 范围语法
    python3 commands/sync.py --tabs 1 --max-units 1          # 验证
    python3 commands/sync.py --legacy                          # 走 v0 旧路径
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from datetime import datetime


def _parse_periods(arg: str) -> list[str]:
    """解析 --periods 参数，支持逗号分隔和范围语法。

    例：
        '2026-01,2026-02,2026-03'   → ['2026-01', '2026-02', '2026-03']
        '2026-01..2026-05'          → ['2026-01', '2026-02', '2026-03', '2026-04', '2026-05']
        '2026-1..2026-5'            → 同上
    """
    if not arg:
        return []
    if '..' in arg:
        # 范围语法
        import re
        m = re.match(r'^(\d{4}-?\d{1,2})\.\.(\d{4}-?\d{1,2})$', arg.strip())
        if not m:
            raise ValueError(f"无效范围: {arg!r}（期望 'YYYY-MM..YYYY-MM'）")
        start, end = m.group(1), m.group(2)
        # 统一格式
        sy, sm = re.match(r'^(\d{4})-?(\d{1,2})$', start).groups()
        ey, em = re.match(r'^(\d{4})-?(\d{1,2})$', end).groups()
        sy, sm, ey, em = int(sy), int(sm), int(ey), int(em)
        periods = []
        y, mo = sy, sm
        while (y, mo) <= (ey, em):
            periods.append(f"{y:04d}-{mo:02d}")
            mo += 1
            if mo > 12:
                mo = 1
                y += 1
        return periods
    return [p.strip() for p in arg.split(',') if p.strip()]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="日照工程造价材料信息同步（v1.1 多期 + API 模式）",
    )
    parser.add_argument("--tabs", default="1,2,3",
                        help="tab 列表（逗号分隔），如 '1,2,3' 或 '1'；默认 3 tab 全跑")
    parser.add_argument("--period", default="",
                        help="指定单个周期（如 '2026-05'）。默认从源站自动探测当前期")
    parser.add_argument("--periods", default="",
                        help="多周期（v1.1）：逗号分隔 '2026-01,2026-02' 或范围 '2026-01..2026-05'")
    parser.add_argument("--run-id", default="",
                        help="指定 run_id（默认自动生成）")
    parser.add_argument("--max-pages", type=int, default=2000,
                        help="最大页数（默认 2000，v1.1 已无实际作用）")
    parser.add_argument("--reset", action="store_true",
                        help="重置本地进度，重新开始")
    parser.add_argument("--max-units", type=int, default=None,
                        help="Collector 路径：只跑前 N 个工作单元（验证用）")
    parser.add_argument("--legacy", action="store_true",
                        help="v0 兼容：走原流式同步（旧生产路径）。默认走 Collector")
    parser.add_argument("--dry-run", action="store_true",
                        help="预览模式（仅 legacy 路径支持）")
    parser.add_argument("--force", action="store_true",
                        help="强制全量同步（仅 legacy 路径支持）")
    args = parser.parse_args()

    if args.legacy:
        print("[v0 兼容路径] 启动流式同步（旧版）")
        from commands.legacy_sync import main as legacy_main
        legacy_main(args)
    else:
        from commands.rizhao_collector import make_collector
        cfg_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'config.yml',
        )
        tabs = [t.strip() for t in args.tabs.split(',') if t.strip()]
        run_id = args.run_id or f"rz_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # 解析 periods：--periods 优先，--period 兼容单期
        if args.periods:
            periods = _parse_periods(args.periods)
        elif args.period:
            periods = [args.period]
        else:
            periods = []  # 自动探测当前期

        print(f"[Collector 路径 v1.1] RizhaoCollector 启动")
        print(f"  tabs={tabs}")
        print(f"  periods={periods or '(auto: 当前期)'}")
        print(f"  run_id={run_id}")

        collector = make_collector(
            cfg_path=cfg_path,
            run_id=run_id,
            periods=periods,
            tabs=tabs,
            max_pages=args.max_pages,
        )
        result = collector.run(reset=args.reset, max_units=args.max_units)
        print(f"\n[Collector 路径 v1.1] 完成: {result}")
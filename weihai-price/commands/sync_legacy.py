#!/usr/bin/env python3
"""威海同步入口（v1.0, 2026-07-04）

默认走 WeihaiCollector（SyncRunner 抽象基类），参考 chongqing v0.9 设计：
- 默认走 Collector 路径
- --legacy 走老 sync.py 主函数（逃生通道）
- ODS 文档 + progress 文档均写入 period_start / period_end / period_days / run_id / last_updated
"""
import argparse
import os
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)


def main():
    parser = argparse.ArgumentParser(description='威海工程造价材料信息同步（默认 Collector 路径）')
    parser.add_argument('--reset', action='store_true', help='重置本地进度，重新开始')
    parser.add_argument('--year', type=int, default=None,
                        help='只入库指定年份（默认走 config.yml 的 default_year，0=不限制）')
    parser.add_argument('--period', default='', help='指定 period（如 2026.1-3月）')
    parser.add_argument('--latest', action='store_true', help='只同步最新一期')
    parser.add_argument('--run-id', default='', help='指定 run_id（默认 weihai_YYYYMMDD_HHMMSS）')
    parser.add_argument('--legacy', action='store_true',
                        help='走老 sync.py 主函数路径（逃生通道，不推荐）')
    args = parser.parse_args()

    # year 默认走 config.yml 的 default_year
    if args.year is None:
        from utils import load_config
        cfg = load_config()
        args.year = cfg.get('sync', {}).get('default_year', 0) or 0

    run_id = args.run_id or f"weihai_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print(f'[weihai] run_id={run_id}  year={args.year}  period={args.period or "全部"}  latest={args.latest}')

    if args.legacy:
        # 老 sync.py 路径（保留作逃生通道）
        from sync_legacy import main as legacy_main
        print(f'[v0.x 兼容路径] 老 sync.py 启动')
        sys.argv = [sys.argv[0], '--period', args.period, '--year', str(args.year),
                    '--latest' if args.latest else '--no-latest']
        if args.reset:
            sys.argv.append('--reset')
        legacy_main()
    else:
        # 默认 Collector 路径
        from weihai_collector import make_collector
        cfg_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'config.yml',
        )
        collector = make_collector(
            cfg_path=cfg_path,
            year=args.year,
            run_id=run_id,
            period_filter=args.period,
            latest=args.latest,
        )
        result = collector.run(reset=args.reset)
        print(f'\n[Collector 路径] 完成: {result}')
        return result


if __name__ == '__main__':
    main()
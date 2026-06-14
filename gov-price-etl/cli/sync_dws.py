#!/usr/bin/env python3
"""cli/sync_dws - DWD → DWS 同步（合一版）

模式（默认 quick）：
  - quick   DWD 有非空 attr 即同步（不调 AI，最快）
  - plain   DWD spec 非空即同步（不调 AI）
  - ai      缺 attr 的 doc 走 AI 补全，再写 DWS

用法：
  ./cli/sync_dws                          # 全量 quick 同步
  ./cli/sync_dws --mode ai --city xian    # AI 补全模式
  ./cli/sync_dws --mode plain --dry-run   # 预览 plain 模式
  ./cli/sync_dws --batch-size 2000
"""
import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from gov_price_etl.config import CITY_CONFIGS, load_config  # noqa: E402
from gov_price_etl.pipeline.dws_sync import (  # noqa: E402
    sync_dws_plain,
    sync_dws_quick,
    sync_dws_with_ai,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="DWD→DWS 同步（合一版）")
    parser.add_argument("--city", default="", help="指定城市（空=全部）")
    parser.add_argument("--mode", default="quick", choices=["quick", "plain", "ai"],
                        help="同步模式（默认 quick）")
    parser.add_argument("--batch-size", type=int, default=None,
                        help="批量大小（默认：quick=1000, plain=500, ai=500）")
    parser.add_argument("--category", default="", help="只同步指定分类（plain 模式有效）")
    parser.add_argument("--dry-run", action="store_true", help="预览模式（不写入）")
    args = parser.parse_args()

    cfg = load_config()
    es_host = cfg["es"]["host"]

    if args.city:
        cities = [args.city] if args.city in CITY_CONFIGS else []
        if not cities:
            print(f"[DWS] 未知城市: {args.city}")
            return 1
    else:
        cities = list(CITY_CONFIGS.keys())

    print(f"[DWS] ES: {es_host}")
    print(f"[DWS] 城市: {', '.join(cities)}")
    print(f"[DWS] 模式: {args.mode} {'(dry-run)' if args.dry_run else ''}")

    if args.mode == "quick":
        bs = args.batch_size or 1000
        # sync_dws_quick 返回 (synced, skipped, failed)
        def _run_quick(host, city, cfg_):
            s, _sk, f = sync_dws_quick(host, city, cfg_, batch_size=bs, dry_run=args.dry_run)
            return s, f
        runner = _run_quick
    elif args.mode == "plain":
        bs = args.batch_size or 500
        runner = lambda host, city, cfg_: sync_dws_plain(host, city, cfg_, batch_size=bs,
                                                         category=args.category, dry_run=args.dry_run)
    else:  # ai
        bs = args.batch_size or 500
        runner = lambda host, city, cfg_: sync_dws_with_ai(host, city, cfg_, batch_size=bs,
                                                            category=args.category, dry_run=args.dry_run)

    start = time.time()
    total_synced = total_failed = 0
    for city in cities:
        cfg_ = CITY_CONFIGS[city]
        synced, failed = runner(es_host, city, cfg_)
        total_synced += synced
        total_failed += failed

    print(f"\n[DWS] 全部完成 ({args.mode}): synced={total_synced}, failed={total_failed}, 用时 {time.time()-start:.1f}s")
    return 0 if total_failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""cli/etl - ODS → DWD → DWS 主入口

用法：
  ./cli/etl                    # 全量（所有城市）
  ./cli/etl --city sichuan     # 只处理指定城市
  ./cli/etl --incremental      # 增量（根据 update_date）
  ./cli/etl --dry-run          # 预览（前100条）
  ./cli/etl --category 瓦      # 只清洗指定分类
  ./cli/etl --batch-size 1000  # 自定义批量大小
  ./cli/etl --no-dws           # 跳过 DWS 同步（只跑 ETL）
"""
import argparse
import sys
import time
from pathlib import Path

# 把 src/ 加入 sys.path，让 `import gov_price_etl` 可用
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from gov_price_etl.config import CITY_CONFIGS, load_config  # noqa: E402
from gov_price_etl.pipeline import run_etl  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="gov-price ETL（多城市）")
    parser.add_argument("--city", default="", help=f"指定城市（空=全部）可用: {', '.join(CITY_CONFIGS.keys())}")
    parser.add_argument("--incremental", action="store_true", help="增量模式")
    parser.add_argument("--dry-run", action="store_true", help="预览模式（不写入）")
    parser.add_argument("--since", default="", help="增量起始日期 YYYY-MM-DD")
    parser.add_argument("--category", default="", help="只清洗指定分类（category 字段过滤）")
    parser.add_argument("--batch-size", type=int, default=500, help="批量大小")
    parser.add_argument("--mark-done", action="store_true", help="批量确认规则（直接标记 needs_spec_parse=False，不走 AI）")
    parser.add_argument("--no-dws", action="store_true", help="跳过 DWS 同步（只跑 ETL）")
    args = parser.parse_args()

    cfg = load_config()
    es_host = cfg["es"]["host"]

    if args.city:
        cities = [args.city] if args.city in CITY_CONFIGS else []
        if not cities:
            print(f"[ETL] 未知城市: {args.city}")
            print(f"可用城市: {', '.join(CITY_CONFIGS.keys())}")
            return 1
    else:
        cities = list(CITY_CONFIGS.keys())

    print(f"[ETL] ES: {es_host}")
    print(f"[ETL] 城市: {', '.join(cities)}")
    print(f"[ETL] 模式: {'增量' if args.incremental else '全量'} {'(dry-run)' if args.dry_run else ''}")

    start = time.time()
    ok, fail = run_etl(
        es_host, cities,
        batch_size=args.batch_size,
        incremental=args.incremental,
        since_date=args.since,
        dry_run=args.dry_run,
        category=args.category,
        mark_done=args.mark_done,
        with_dws=not args.no_dws,
    )
    print(f"[ETL] 耗时 {time.time()-start:.1f}s | ok={ok}, fail={fail}")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())

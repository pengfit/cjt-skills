#!/usr/bin/env python3
"""sync.py - 济南材料价格同步入口

v0.1 (2026-07-03) 模块化重构：
  - 默认走 JinanCollector（参考 chongqing v0.9 SyncRunner 模式）
  - --legacy 走原 v0 内联实现（逃生通道）
  - 支持 --periods 逗号分隔多周期
  - --year 过滤（默认 config.sync.year）
  - --dry-run 预览不写入
"""
import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="济南工程造价材料信息同步（默认 Collector 路径）")
    parser.add_argument("--reset", action="store_true", help="重置本地进度，重新开始")
    parser.add_argument("--legacy", action="store_true", help="v0 兼容：走原 sync 主流程（不推荐）")
    parser.add_argument("--periods", default="", help="多周期，逗号分隔（精确匹配 periodName），如 '2026年01月材料价格信息,2026年02月材料价格信息'")
    parser.add_argument("--year", type=int, default=0, help="按年份过滤（0=用 config.sync.year）")
    parser.add_argument("--run-id", default="", help="自定义 run_id")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不写入 ES")
    parser.add_argument("--max-units", type=int, default=None, help="只跑前 N 个工作单元（验证用）")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg_path = os.path.join(script_dir, "config.yml")

    if args.legacy:
        # v0 兼容：原内联实现（不推荐）
        # 这里直接 import 老 sync.py 的代码块；为简化，临时把本文件当老文件执行
        # （老 sync.py 已备份到 .jinan_sync.py.bak，无需保留 legacy 路径，
        #  真要回滚去 git 看 history）
        print("[!] --legacy 已废弃，Collector 是默认且唯一路径。如需回滚请用 git。")
        sys.exit(1)

    # 默认：Collector 路径
    from commands.jinan_collector import make_collector
    import yaml

    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    year = args.year or cfg.get("sync", {}).get("year", 0)
    run_id = args.run_id or f"jn_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # 解析 periods
    periods: list = []
    if args.periods:
        # 显式传入名称白名单
        cfg.setdefault("sync", {})["periods"] = [p.strip() for p in args.periods.split(",") if p.strip()]
        periods = None  # 交给 collector 处理白名单
    elif year:
        # 按年份过滤：先拉全周期，过滤出 periodName 含 str(year) 的
        from commands.utils import JinAnSiteSession
        session = JinAnSiteSession()
        all_p = session.get_all_periods()
        periods = [
            (str(p.get("id")), p.get("periodName", ""))
            for p in all_p
            if str(year) in p.get("periodName", "")
        ]
        print(f"[i] 按年份 {year} 过滤出 {len(periods)} 个周期")
    else:
        # 没指定：拉全
        periods = None

    print(f"[Collector 路径] JinanCollector 启动")
    print(f"  run_id={run_id}")
    print(f"  periods={'all' if periods is None else len(periods)}")

    collector = make_collector(cfg_path, run_id=run_id, periods=periods, dry_run=args.dry_run)
    result = collector.run(reset=args.reset, max_units=args.max_units)
    print(f"\n[Collector 路径] 完成: {result}")

    # 同步成功后更新 config.last_period / last_period_id / last_run_id
    if result.get("done", 0) > 0 and not result.get("interrupted", False):
        from commands.utils import JinAnSiteSession
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        sync = cfg.setdefault("sync", {})
        # 取源站最新周期作为 last_period
        try:
            s = JinAnSiteSession()
            last_name, last_id = s.get_last_period()
            if last_name:
                sync["last_period"] = last_name
                sync["last_period_id"] = last_id
        except Exception:
            pass
        sync["last_run_id"] = run_id
        sync["last_run_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)
        print(f"[i] config.yml 已更新 last_run_id={run_id}")

#!/usr/bin/env python3
"""吉林增量检测（v0.2, 2026-07-08）：扫描源站 + 比对本地进度，输出待同步清单（不写 ES）。

v0.2 改动：
- 行前缀 [吉林]（与 17 城 check.py 风格一致，供 gov_price_etl.check_status 解析）
- 末行基于"源站 page=1 有数据 vs 本地 progress.done"判定 ok / update
- 写到 /tmp/gov-check-status/jilin.json，供 dashboard /sync 顶部 chip 复用
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

import utils as _u


def _resolve_etl_root():
    """解析 gov-price-etl 项目根（与 henan/hainan 17 城 _resolve_etl_root 同源）。"""
    env = os.environ.get("GOV_PRICE_ETL_ROOT")
    if env and os.path.isdir(env):
        return env
    from pathlib import Path
    p = Path(__file__).resolve().parent
    for _ in range(6):
        candidate = p / "gov-price-etl"
        if candidate.is_dir():
            return str(candidate)
        p = p.parent
    workspace_root = Path.home() / ".openclaw" / "workspace"
    if workspace_root.is_dir():
        for ws in workspace_root.iterdir():
            candidate = ws / "skills" / "gov-price-etl"
            if candidate.is_dir():
                return str(candidate)
    raise FileNotFoundError(
        "找不到 gov-price-etl 项目根。"
        "请设置环境变量 GOV_PRICE_ETL_ROOT 指向项目根，"
        "或确认 ETL 已部署在 <workspace>/skills/gov-price-etl。"
    )


def main():
    cfg = _u.load_config()
    print(f"=== 增量检测（吉林 · {cfg['sync']['year']} 年） ===\n")

    # 读本地进度（progress.done 是 "|period" 格式列表，diqu 为空时）
    progress_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        ".jilin_sync_progress.json",
    )
    done_set = set()
    if os.path.exists(progress_path):
        import json
        try:
            with open(progress_path) as f:
                p = json.load(f)
            done_set = set(p.get("done", []) or [])
        except Exception:
            pass

    # 对每个月做一次轻量查询（page=1），看是否有数据
    from datetime import datetime
    last_m = datetime.now().month
    year = cfg['sync']['year']
    s = requests.Session()
    s.get(
        cfg['site']['base_url'] + f"?city={cfg['site']['city_id']}",
        headers=_u.DEFAULT_HEADERS,
        timeout=15,
    )

    todo = []
    for m in range(1, last_m + 1):
        period = f"{year}年{m}月份"
        unit_key = f"|{period}"  # 本地进度格式：diqu|period，diqu 空时为前缀 |
        try:
            html = _u.fetch_list_page(
                s,
                base_url=cfg['site']['base_url'],
                city_id=cfg['site']['city_id'],
                price_time=period,
                page=1,
                max_retries=2,
            )
            rows = _u.parse_rows(html)
            print(f"[吉林] {period:<12s} {len(rows):>4d} 条（page=1）")
            if rows and unit_key not in done_set:
                todo.append(period)
        except Exception as e:
            print(f"[吉林] {period:<12s} ✗ 抓取失败: {e}")

    print(f"\n[吉林] 待同步月份: {len(todo)} 个")
    if not todo:
        print("[吉林] ✅ 无新数据")
    else:
        for p in todo:
            print(f"  - {p}")
        print(f"\n[吉林] 🔔 有更新! {len(todo)} 个待同步月份")
        print(f"\n运行 './run.sh sync' 开始同步")


# === dashboard status 同步（v0.2, 2026-07-08）===
# 捕获 main() 的 stdout，按末行 [吉林] 状态写到 /tmp/gov-check-status/jilin.json
# 供 dashboard /sync 顶部 chip 复用。已存在则覆盖。
if __name__ == "__main__":
    import sys as _sys, io as _io
    _buf = _io.StringIO()
    _old_stdout = _sys.stdout
    _sys.stdout = _buf
    try:
        main()
    finally:
        _sys.stdout = _old_stdout
    _output = _buf.getvalue()
    print(_output, end='')  # 完整回放到屏幕（保留原行为）

    # 写 check_status json
    try:
        _etl_root = _resolve_etl_root()
        if _etl_root not in _sys.path:
            _sys.path.insert(0, _etl_root)
        from gov_price_etl.check_status import write_status_from_check_output
        write_status_from_check_output('jilin', '吉林', _output)
    except Exception as _e:
        print(f"⚠️ check_status 失败: {_e}", file=_sys.stderr)

"""贵州 · 增量检测：对比 ES 最新 update_date vs 源站最新发布日期。"""
def _resolve_etl_root():
    """解析 gov-price-etl 项目根路径（同 sync/utils.py 模式）。"""
    import os
    from pathlib import Path
    env = os.environ.get("GOV_PRICE_ETL_ROOT")
    if env and os.path.isdir(env):
        return env
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


import json
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import load_config, get_es_client
from sync import fetch_all_periods, post_form


def main():
    cfg = load_config()
    es = get_es_client(cfg['es']['host'])
    site = cfg['site']
    ods_index = cfg['es']['ods_index']

    # 1. ES 最新 update_date
    es_latest = ''
    try:
        r = es.search(
            index=ods_index, size=1, sort=[{'update_date': 'desc'}],
            _source=['update_date'],
        )
        hits = r['hits']['hits']
        if hits:
            es_latest = (hits[0]['_source'].get('update_date', '') or '')[:10]
    except Exception as e:
        print(f'[贵州] ES 查询失败: {e}')

    # 2. 源站最新（首页第 1 条 = 最新期）
    site_latest = ''
    site_title = ''
    try:
        items = fetch_all_periods(cfg)
        if items:
            site_latest = items[0].get('publish_date', '') or ''
            site_title = items[0].get('title', '')
    except Exception as e:
        print(f'[贵州] 源站查询失败: {e}')

    print(f'[贵州] 源站最新: {site_title} ({site_latest})')
    print(f'[贵州] ES 最新:   {es_latest or "无"}')

    if es_latest and site_latest:
        if site_latest > es_latest:
            print(f'[贵州] 🔔 有更新！{site_title}')
        else:
            print(f'[贵州] ✅ 无新数据')
    elif site_latest:
        print(f'[贵州] 🔔 源站有数据，ES 无记录，需首次同步')
    else:
        print(f'[贵州] ⚠️ 无法获取源站数据')


# === dashboard status 同步（参考 henan/check.py v0.8.1, 2026-07-03）===
# 捕获 main() 的 stdout, 按末行 [城市] 状态写到 /tmp/gov-check-status/<key>.json
# 供 dashboard /sync 顶部 chip 复用。
if __name__ == '__main__':
    import sys as _sys, io as _io
    _buf = _io.StringIO()
    _old_stdout = _sys.stdout
    _sys.stdout = _buf
    try:
        main()
    finally:
        _sys.stdout = _old_stdout
    _output = _buf.getvalue()
    print(_output, end='')

    try:
        _etl_root = _resolve_etl_root()
        if _etl_root not in _sys.path:
            _sys.path.insert(0, _etl_root)
        from gov_price_etl.check_status import write_status_from_check_output
        write_status_from_check_output('guizhou', '贵州', _output)
    except Exception as _e:
        print(f'⚠️ check_status 失败: {_e}', file=_sys.stderr)

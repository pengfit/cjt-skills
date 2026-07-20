import os
STATUS_DIR = os.environ.get("GOV_CHECK_STATUS_DIR", "/tmp/gov-check-status")
SUMMARY_DIR = os.environ.get("GOV_PRICE_SUMMARY_DIR", "/tmp/gov-price-summary")

"""山西 · 增量检测:对比 ES 最新 update_date vs 源站最新发布日期。"""
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import load_config, get_es_client
from sync import fetch_all_periods, should_include


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
        print(f'[山西] ES 查询失败: {e}')

    # 2. 源站最新（首页第 1 条 = 最新期, 取通过过滤的第 1 条）
    site_latest = ''
    site_title = ''
    try:
        items = fetch_all_periods(cfg)
        for it in items:
            include, _ = should_include(it, cfg)
            if include:
                site_latest = it.get('publish_date', '') or ''
                site_title = it.get('title', '')
                break
    except Exception as e:
        print(f'[山西] 源站查询失败: {e}')

    print(f'[山西] 源站最新: {site_title} ({site_latest})')
    print(f'[山西] ES 最新:   {es_latest or "无"}')

    if es_latest and site_latest:
        if site_latest > es_latest:
            print(f'[山西] 🔔 有更新！{site_title}')
        else:
            print(f'[山西] ✅ 无新数据')
    elif site_latest:
        print(f'[山西] 🔔 源站有数据，ES 无记录，需首次同步')
    else:
        print(f'[山西] ⚠️ 无法获取源站数据')


# === dashboard status 同步（参考 guizhou/check.py v0.8.1, 2026-07-03）===
# 捕获 main() 的 stdout, 按末行 [城市] 状态写到 STATUS_DIR/<key>.json
# 供 dashboard /sync 顶部 chip 复用。
if __name__ == '__main__':
    import io
    _buf = io.StringIO()
    _old_stdout = sys.stdout
    sys.stdout = _buf
    try:
        main()
    finally:
        sys.stdout = _old_stdout
    _output = _buf.getvalue()
    print(_output, end='')

    try:
        # 复用 _resolve_etl_root 模式找 ETL
        _etl_root = None
        _env = os.environ.get('GOV_PRICE_ETL_ROOT')
        if _env and os.path.isdir(_env):
            _etl_root = _env
        else:
            _p = Path(__file__).resolve().parent
            for _ in range(6):
                _cand = _p / 'gov-price-etl'
                if _cand.is_dir():
                    _etl_root = str(_cand)
                    break
                _p = _p.parent
        if _etl_root and _etl_root not in sys.path:
            sys.path.insert(0, _etl_root)
        from gov_price_etl.check_status import write_status_from_check_output
        write_status_from_check_output('shanxi', '山西', _output)
    except Exception as _e:
        print(f'⚠️ check_status 失败: {_e}', file=sys.stderr)
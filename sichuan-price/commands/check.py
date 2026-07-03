"""四川 - 增量检测：对比 ES 最新 period vs 源站最新周期"""
import sys, os, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(SCRIPT_DIR, 'config.yml')

from commands.utils import load_config, get_all_periods, get_latest_period
from elasticsearch import Elasticsearch

requests.packages.urllib3.disable_warnings()


def main():
    cfg = load_config(CONFIG_PATH)
    es = Elasticsearch(cfg['es']['host'])
    ods_index = cfg['es']['index']

    # 1. 获取 ES 最新 update_date
    es_latest = ''
    try:
        r = es.search(index=ods_index, size=1, sort=[{'update_date': 'desc'}],
                       _source=['update_date', 'period'])
        hits = r['hits']['hits']
        if hits:
            es_latest = hits[0]['_source'].get('update_date', '') or ''
    except Exception as e:
        print(f'[四川] ES 查询失败: {e}')

    # 2. 获取源站最新周期
    periods = get_all_periods()
    active = [p for p in periods if p.get('State') == 1]
    if not active:
        print('[四川] 未找到有效周期')
        return

    latest = max(active, key=lambda x: x.get('PeriodNo', 0))
    site_period = latest['PeriodName']

    print(f'[四川] 源站最新周期: {site_period}')
    print(f'[四川] ES 最新入库:   {es_latest or "无"}')

    if es_latest:
        es_month = es_latest[:7].replace('-', '年') + '月'
        if site_period > es_month:
            print(f'[四川] 🔔 有更新！源站 {site_period}')
        else:
            print(f'[四川] ✅ 无新数据')
    else:
        print(f'[四川] 🔔 ES 无数据，需首次同步')


# === dashboard status 同步（v0.8.1, 2026-07-03）===
# 捕获 main() 的 stdout，按末行 [城市] 状态写到 /tmp/gov-check-status/<key>.json
# 供 dashboard /sync 顶部 chip 复用。已存在则覆盖。
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
    print(_output, end='')  # 完整回放到屏幕（保留原行为）

    # 写 check_status json
    try:
        if '/Users/pengfit/.openclaw/workspace/skills/gov-price-etl' not in _sys.path:
            _sys.path.insert(0, '/Users/pengfit/.openclaw/workspace/skills/gov-price-etl')
        from gov_price_etl.check_status import write_status_from_check_output
        write_status_from_check_output('sichuan', '四川', _output)
    except Exception as _e:
        print(f'⚠️ check_status 失败: {_e}', file=_sys.stderr)

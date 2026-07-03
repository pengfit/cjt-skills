"""济南 - 增量检测：对比 ES 最新入库周期 vs 源站最新周期"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(SCRIPT_DIR, 'config.yml')

from commands.utils import JinAnSiteSession, load_config
from elasticsearch import Elasticsearch


def main():
    cfg = load_config(CONFIG_PATH)
    es = Elasticsearch(cfg['es']['host'])
    ods_index = cfg['es']['index']
    session = JinAnSiteSession()

    # 1. 获取 ES 最新 period
    es_latest_period = ''
    try:
        r = es.search(index=ods_index, size=1, sort=[{'update_date': 'desc'}],
                       _source=['update_date', 'period'])
        hits = r['hits']['hits']
        if hits:
            es_latest_period = hits[0]['_source'].get('period', '') or ''
    except Exception as e:
        print(f'[济南] ES 查询失败: {e}')

    # 2. 获取源站最新周期
    site_period = ''
    try:
        period_name, period_id = session.get_last_period()
        site_period = period_name
    except Exception as e:
        site_period = cfg.get('sync', {}).get('last_period', '')
        print(f'[济南] 源站查询异常，使用 config: {e}')

    print(f'[济南] 源站最新周期: {site_period}')
    print(f'[济南] ES 最新入库:   {es_latest_period or "无"}')

    if site_period and (not es_latest_period or site_period > es_latest_period):
        print(f'[济南] 🔔 有更新！源站 {site_period}')
    else:
        print(f'[济南] ✅ 无新数据')


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
        write_status_from_check_output('jinan', '济南', _output)
    except Exception as _e:
        print(f'⚠️ check_status 失败: {_e}', file=_sys.stderr)

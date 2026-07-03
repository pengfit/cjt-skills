"""呼和浩特 - 增量检测：对比 ES 最新 update_date vs 源站最新发布日期"""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import load_config, get_es_client
from sync import fetch_all_periods


def main():
    cfg = load_config()
    es = get_es_client(cfg['es']['host'])
    ods_index = cfg['es']['ods_index']

    # 1. 获取 ES 最新 update_date
    es_latest = ''
    try:
        r = es.search(
            index=ods_index, size=1,
            sort=[{'update_date': 'desc'}],
            _source=['update_date'],
        )
        hits = r['hits']['hits']
        if hits:
            es_latest = hits[0]['_source'].get('update_date', '') or ''
    except Exception as e:
        print(f'[呼和浩特] ES 查询失败: {e}')

    # 2. 获取源站最新发布（仅过滤"信息价"）
    site_latest = ''
    site_title = ''
    try:
        items = fetch_all_periods(cfg)
        journal_kw = cfg.get('journal_keyword', '')
        if journal_kw:
            items = [it for it in items if journal_kw in it['title']]
        if items:
            items_sorted = sorted(items, key=lambda x: x.get('publish_date', ''), reverse=True)
            site_latest = items_sorted[0].get('publish_date', '')
            site_title = items_sorted[0].get('title', '')
    except Exception as e:
        print(f'[呼和浩特] 源站查询失败: {e}')

    print(f'[呼和浩特] 源站最新: {site_title} ({site_latest})')
    print(f'[呼和浩特] ES 最新:   {es_latest or "无"}')

    if es_latest and site_latest:
        if site_latest > str(es_latest)[:10]:
            print(f'[呼和浩特] 🔔 有更新！{site_title}')
        else:
            print(f'[呼和浩特] ✅ 无新数据')
    elif site_latest:
        print(f'[呼和浩特] 🔔 源站有数据，ES 无记录，需首次同步')
    else:
        print(f'[呼和浩特] ⚠️ 无法获取源站数据')


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
        write_status_from_check_output('huhehaote', '呼和浩特', _output)
    except Exception as _e:
        print(f'⚠️ check_status 失败: {_e}', file=_sys.stderr)

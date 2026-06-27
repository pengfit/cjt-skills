"""湖南 - 增量检测：对比 ES 最新 update_date vs 源站最新发布日期"""
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
        print(f'[hunan] ES 查询失败: {e}')

    # 2. 获取源站最新发布
    site_latest = ''
    site_title = ''
    try:
        items = fetch_all_periods(cfg)
        keywords = cfg.get('journal_keywords', [])
        if keywords:
            items = [it for it in items if any(kw in it['title'] for kw in keywords)]
        if items:
            items_sorted = sorted(items, key=lambda x: x.get('title', ''), reverse=True)
            site_title = items_sorted[0].get('title', '')
            site_latest = site_title[:30]
    except Exception as e:
        print(f'[hunan] 源站查询失败: {e}')

    print(f'[hunan] 源站最新: {site_title}')
    print(f'[hunan] ES 最新:   {es_latest or "无"}')

    if site_title:
        if not es_latest:
            print(f'[hunan] 🔔 源站有数据，ES 无记录，需首次同步')
        else:
            print(f'[hunan] ✅ ES 有数据，按 --year / --period 增量同步')


if __name__ == '__main__':
    main()
"""海南 - 增量检测：对比 ES 最新 update_date vs 源站最新发布日期"""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import load_config, get_es_client
from parser import fetch_all_periods


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
        print(f'[海南] ES 查询失败: {e}')

    # 2. 获取源站最新发布
    site_latest = ''
    site_title = ''
    try:
        items = fetch_all_periods(cfg)
        if items:
            # 列表按发布日期降序，第一项最新
            items_sorted = sorted(items, key=lambda x: x.get('publish_date', ''), reverse=True)
            site_latest = items_sorted[0].get('publish_date', '')
            site_title = items_sorted[0].get('title', '')
    except Exception as e:
        print(f'[海南] 源站查询失败: {e}')

    print(f'[海南] 源站最新: {site_title} ({site_latest})')
    print(f'[海南] ES 最新:   {es_latest or "无"}')

    if es_latest and site_latest:
        if site_latest > str(es_latest)[:10]:
            print(f'[海南] 🔔 有更新！{site_title}')
        else:
            print(f'[海南] ✅ 无新数据')
    elif site_latest:
        print(f'[海南] 🔔 源站有数据，ES 无记录，需首次同步')
    else:
        print(f'[海南] ⚠️ 无法获取源站数据')


if __name__ == '__main__':
    main()
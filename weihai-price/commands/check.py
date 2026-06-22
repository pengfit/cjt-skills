"""威海 - 增量检测：对比 ES 最新 update_date vs 源站最新发布日期"""
import os
import sys
from urllib.parse import urljoin

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import load_config, get_es_client, fetch_list_page
from sync import fetch_all_periods, _is_price_entry


def main():
    cfg = load_config()
    es = get_es_client(cfg['es']['host'])
    ods_index = cfg['es']['ods_index']

    # 1. 获取 ES 最新 update_date
    es_latest = ''
    try:
        r = es.search(index=ods_index, size=1, sort=[{'update_date': 'desc'}],
                      _source=['update_date'])
        hits = r['hits']['hits']
        if hits:
            es_latest = hits[0]['_source'].get('update_date', '') or ''
    except Exception as e:
        print(f'[威海] ES 查询失败: {e}')

    # 2. 抓源站通知公告列表，找最新材料价目条目
    site_latest = ''
    site_title = ''
    try:
        items = fetch_all_periods(cfg)
        price_items = [it for it in items if _is_price_entry(it['title'])]
        if price_items:
            site_latest = price_items[0]['publish_date']
            site_title = price_items[0]['title']
    except Exception as e:
        print(f'[威海] 源站查询失败: {e}')

    print(f'[威海] 源站最新价目: {site_title} ({site_latest})')
    print(f'[威海] ES 最新:       {es_latest or "无"}')

    if es_latest and site_latest:
        if site_latest > str(es_latest)[:10]:
            print(f'[威海] 🔔 有更新！{site_title}')
        else:
            print(f'[威海] ✅ 无新数据')
    elif site_latest:
        print(f'[威海] 🔔 源站有数据，ES 无记录，需首次同步')
    else:
        print(f'[威海] ⚠️ 无法获取源站数据')


if __name__ == '__main__':
    main()

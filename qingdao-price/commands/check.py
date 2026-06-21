"""青岛 - 增量检测：对比 ES 最新 update_date vs 源站最新发布日期"""
import sys, os, re
from bs4 import BeautifulSoup

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from utils import load_config, get_es_client, fetch_html


def main():
    cfg = load_config()
    es = get_es_client(cfg['es']['host'])
    site = cfg['site']
    base = site['base_url']
    ods_index = cfg['es']['ods_index']
    headers = {'User-Agent': site['user_agent']}

    # 1. 获取 ES 最新 update_date
    es_latest = ''
    try:
        r = es.search(index=ods_index, size=1, sort=[{'update_date': 'desc'}],
                       _source=['update_date'])
        hits = r['hits']['hits']
        if hits:
            es_latest = hits[0]['_source'].get('update_date', '') or ''
    except Exception as e:
        print(f'[青岛] ES 查询失败: {e}')

    # 2. 获取源站最新发布
    site_latest = ''
    site_title = ''
    try:
        list_url = base + site['list_path']
        html = fetch_html(list_url, headers=headers)
        soup = BeautifulSoup(html, 'html.parser')
        first_li = soup.select_one('li[trs-attr="chip"]')
        if first_li:
            a = first_li.select_one('a[title]')
            if a:
                site_title = a.get('title', '')
            date_el = first_li.select_one('div.div_list_li_width_right')
            if date_el:
                m = re.search(r'\[?(\d{4}-\d{2}-\d{2})\]?', date_el.get_text(strip=True))
                if m:
                    site_latest = m.group(1)
    except Exception as e:
        print(f'[青岛] 源站查询失败: {e}')

    print(f'[青岛] 源站最新: {site_title} ({site_latest})')
    print(f'[青岛] ES 最新:   {es_latest or "无"}')

    if es_latest and site_latest:
        if site_latest > str(es_latest)[:10]:
            print(f'[青岛] 🔔 有更新！{site_title}')
        else:
            print(f'[青岛] ✅ 无新数据')
    elif site_latest:
        print(f'[青岛] 🔔 源站有数据，ES 无记录，需首次同步')
    else:
        print(f'[青岛] ⚠️ 无法获取源站数据')


if __name__ == '__main__':
    main()

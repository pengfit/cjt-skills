"""西安 - 增量检测：对比 ES 最新入库日期 vs 源站各区县最新日期"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(SCRIPT_DIR, 'config.yml')

from commands.utils import SiteSession, parse_page_date, COUNTY_CODES, load_config, list_all_years
from elasticsearch import Elasticsearch


def main():
    cfg = load_config(CONFIG_PATH)
    es = Elasticsearch(cfg['es']['host'])
    ods_index = cfg['es']['index']
    sess = SiteSession()
    counties = list(COUNTY_CODES.keys())

    # 1. 获取 ES 最新 update_date
    es_latest = None
    try:
        r = es.search(index=ods_index, size=1, sort=[{'update_date': 'desc'}],
                       _source=['update_date'])
        hits = r['hits']['hits']
        if hits:
            es_latest = hits[0]['_source'].get('update_date', '')
    except Exception as e:
        print(f'[西安] ES 查询失败: {e}')

    # 2. 获取源站各区县最新日期
    site_latest = ''
    site_latest_county = ''
    for county in counties:
        ys = list_all_years(county, sess)
        if not ys:
            continue
        max_year = max(ys)
        periods = sess.list_periods(county, max_year)
        if not periods:
            continue
        latest_period = periods[-1]
        html = sess.fetch(county, page=1, gkbh=latest_period.get('id', ''))
        date_str = parse_page_date(html) if html else ''
        if date_str and (not site_latest or date_str > site_latest):
            site_latest = date_str
            site_latest_county = county

    # 3. 输出
    print(f'[西安] 源站最新日期: {site_latest} ({site_latest_county})')
    print(f'[西安] ES 最新入库:   {es_latest or "无"}')

    if site_latest and (not es_latest or site_latest > str(es_latest)[:10]):
        print(f'[西安] 🔔 有更新！源站 {site_latest} > ES {es_latest}')
    else:
        print(f'[西安] ✅ 无新数据')


if __name__ == '__main__':
    main()

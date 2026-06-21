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


if __name__ == '__main__':
    main()

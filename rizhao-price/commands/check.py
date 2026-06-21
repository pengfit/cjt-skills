"""日照 - 增量检测：对比 ES 最新 update_date vs 源站最新周期"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(SCRIPT_DIR, 'config.yml')

from commands.utils import load_config
from elasticsearch import Elasticsearch


def main():
    cfg = load_config(CONFIG_PATH)
    es = Elasticsearch(cfg['es']['host'])
    ods_index = cfg['es']['index']
    sync_cfg = cfg.get('sync', {})

    # 1. 获取 ES 最新 update_date
    es_latest = ''
    try:
        r = es.search(index=ods_index, size=1, sort=[{'update_date': 'desc'}],
                       _source=['update_date', 'period'])
        hits = r['hits']['hits']
        if hits:
            es_latest = hits[0]['_source'].get('update_date', '') or ''
    except Exception as e:
        print(f'[日照] ES 查询失败: {e}')

    # 2. 获取源站最新周期
    last_period = sync_cfg.get('last_period', '')

    print(f'[日照] 源站最新周期: {last_period}')
    print(f'[日照] ES 最新入库:   {es_latest or "无"}')

    if es_latest:
        # 简单日期对比：ES 最新日期 vs 当日
        from datetime import datetime
        es_str = str(es_latest)[:10]
        es_dt = datetime.strptime(es_str, '%Y-%m-%d')
        days_ago = (datetime.now() - es_dt).days
        if days_ago > 30:
            print(f'[日照] ⚠️ 最新入库 {days_ago} 天前，可能需检查')
        else:
            print(f'[日照] ✅ 最新入库 {days_ago} 天前')
    else:
        print(f'[日照] 🔔 ES 无数据，需首次同步')


if __name__ == '__main__':
    main()

"""济南工程造价材料信息 - 状态查看"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from datetime import datetime
from commands.utils import load_config


def main():
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config = load_config(os.path.join(script_dir, 'config.yml'))
    es_host = config.get('es', {}).get('host', 'http://localhost:59200')
    es_index = config.get('es', {}).get('index', 'ods_material_jinan_price')
    progress_index = config.get('es', {}).get('progress_index', 'ods_material_jinan_price_sync_progress')

    # 文档总数
    try:
        r = requests.get(f"{es_host}/{es_index}/_count", timeout=10, verify=False)
        count = r.json().get('count', '?')
    except Exception:
        count = '?'
    print(f"ES 文档总数: {count}")

    # 最新同步周期
    last_period = config.get('sync', {}).get('last_period', '')
    last_period_id = config.get('sync', {}).get('last_period_id', '')
    print(f"最新同步周期: {last_period or '(无)'} (id={last_period_id or '无'})")

    # 本地进度
    progress_path = os.path.join(script_dir, '.jinan_sync_progress.json')
    if os.path.exists(progress_path):
        with open(progress_path) as f:
            prog = json.load(f)
        print(f"\n本地进度:")
        print(f"  分类: {prog.get('catalogue_id', '无')}")
        print(f"  周期: {prog.get('period_name', '无')}")
        print(f"  页码: {prog.get('page', '无')}")
        print(f"  记录: {prog.get('total_records', '无')}")
        print(f"  已写: {prog.get('docs_written', '无')}")
        print(f"  保存: {prog.get('saved_at', '无')}")

    # ES 进度
    try:
        r2 = requests.get(f"{es_host}/{progress_index}/_search", json={
            "size": 1, "sort": [{"last_updated": "desc"}],
            "query": {"match_all": {}}
        }, timeout=10, verify=False)
        hits = r2.json().get('hits', {}).get('hits', [])
        if hits:
            src = hits[0]['_source']
            print(f"\nES 同步进度:")
            print(f"  状态: {src.get('status', '?')}")
            print(f"  分类: {src.get('catalogue_name', '?')}")
            print(f"  页码: {src.get('current_page', '?')}/{src.get('total_pages', '?')}")
            print(f"  百分比: {src.get('percent', '?')}%")
            print(f"  已写: {src.get('docs_written', '?')}")
            print(f"  耗时: {src.get('duration_sec', '?')}s")
            print(f"  更新时间: {src.get('last_updated', '?')}")
    except Exception as e:
        print(f"\nES 进度读取失败: {e}")


if __name__ == '__main__':
    main()

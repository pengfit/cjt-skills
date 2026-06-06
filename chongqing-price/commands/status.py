#!/usr/bin/env python3
"""查看同步状态"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import warnings
warnings.filterwarnings('ignore')
import requests
from commands.utils import load_config

ES_HOST = "http://localhost:59200"


def main():
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config = load_config(os.path.join(script_dir, 'config.yml'))
    es_host = config.get('es', {}).get('host', ES_HOST)
    progress_index = config.get('es', {}).get('progress_index', 'ods_chongqing_price_progress')

    # 本地进度文件
    local_path = os.path.join(script_dir, '.chongqing_sync_progress.json')
    if os.path.exists(local_path):
        with open(local_path, encoding="utf-8") as f:
            prog = json.load(f)
        print("=== 本地进度 ===")
        print(f"  run_id: {prog.get('run_id', 'N/A')}")
        print(f"  保存时间: {prog.get('saved_at', 'N/A')}")
        # 各 source 进度
        for key, label in [('done', '已完成的'), ('done_district', '区县材料'), ('done_mortar', '预拌砂浆'), ('done_citywide', '重庆材料信息价')]:
            items = prog.get(key, [])
            if items or key == 'done':
                print(f"  {label}: {len(items)} 个")

    # ES 进度索引
    try:
        r = requests.get(
            f"{es_host}/{progress_index}/_search?size=10&sort=last_updated:desc",
            timeout=10, verify=False
        )
        if r.status_code == 200:
            hits = r.json().get("hits", {}).get("hits", [])
            if hits:
                print(f"\n=== ES 进度记录 ({len(hits)} 条最新) ===")
                for h in hits:
                    src = h.get("_source", {})
                    area = src.get('area', '')
                    # area 格式: "来源-名称"，尝试拆分
                    if '-' in area:
                        idx = area.index('-')
                        source_tag = area[:idx]
                        name = area[idx+1:]
                        display = f"[{source_tag}] {name}"
                    else:
                        display = area
                    print(f"  {display} | {src.get('status')} | {src.get('docs_written')} docs | {src.get('last_updated')}")
            else:
                print("\n=== ES 进度: 暂无记录 ===")
        else:
            print(f"\n=== ES 查询失败: {r.status_code} ===")
    except Exception as e:
        print(f"\n=== ES 连接失败: {e} ===")

    # config 中的 last_period
    last_period = config.get('sync', {}).get('last_period', 'N/A')
    print(f"\nconfig 中上次同步周期: {last_period}")


if __name__ == '__main__':
    main()
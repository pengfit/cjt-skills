"""济南工程造价材料信息 - 连接测试"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from commands.utils import load_config


def main():
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config = load_config(os.path.join(script_dir, 'config.yml'))
    es_host = config.get('es', {}).get('host', 'http://localhost:59200')
    es_index = config.get('es', {}).get('index', 'ods_material_jinan_price')

    # ES 测试
    print("[i] 测试 ES 连接...")
    try:
        r = requests.get(f"{es_host}/_cluster/health", timeout=10, verify=False)
        health = r.json()
        print(f"  Cluster: {health.get('cluster_name')} / {health.get('status')}")
        r2 = requests.get(f"{es_host}/{es_index}/_mapping", timeout=10, verify=False)
        if r2.status_code == 200:
            print(f"  索引 {es_index}: 已存在")
        else:
            print(f"  索引 {es_index}: 不存在（同步时会自动创建）")
    except Exception as e:
        print(f"  [!] ES 连接失败: {e}")

    # 网站测试
    print("\n[i] 测试济南网站连接...")
    try:
        r3 = requests.get("http://jnxxj.jngczjxh.com:5020/cj/", timeout=10, verify=False)
        print(f"  状态码: {r3.status_code}")
        if r3.status_code == 200:
            print(f"  网站可访问")
        else:
            print(f"  [!] 网站返回非200状态")
    except Exception as e:
        print(f"  [!] 网站连接失败: {e}")


if __name__ == '__main__':
    main()

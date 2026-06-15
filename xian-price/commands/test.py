"""测试 ES 连接"""
import sys
import os
import requests

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPT_DIR)

try:
    import urllib3
    urllib3.disable_warnings()
except Exception:
    pass


def main():
    script_dir = __file__.rsplit('/', 1)[0]
    config_path = f"{script_dir}/../config.yml"

    from commands.utils import load_config
    config = load_config(config_path)

    es_host = config['es']['host']
    es_index = config['es']['index']

    print(f"ES Host: {es_host}")
    print(f"Index:   {es_index}")

    try:
        resp = requests.get(es_host, timeout=10, verify=False)
        print(f"Cluster: {resp.json().get('cluster_name','?')}")
        print(f"Status:  {resp.json().get('status','?')}")
    except Exception as e:
        print(f"[!] 连接失败: {e}")
        sys.exit(1)

    # 检查索引
    try:
        resp = requests.get(f"{es_host}/{es_index}", timeout=10, verify=False)
        if resp.status_code == 200:
            info = resp.json()
            print(f"\n[✓] 索引存在")
            print(f"    文档数: {info.get('count','?')}")
            prim = info.get('number_of_primary_shards', '?')
            repl = info.get('number_of_replicas', '?')
            print(f"    主分片: {prim}")
            print(f"    副本:   {repl}")
        else:
            print(f"[!] 索引不存在: {resp.status_code}")
    except Exception as e:
        print(f"[!] 索引查询失败: {e}")


if __name__ == '__main__':
    main()

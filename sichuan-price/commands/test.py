#!/usr/bin/env python3
"""测试 ES 连接"""
import sys, os, yaml, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
config_path = os.path.join(script_dir, 'config.yml')

with open(config_path) as f:
    config = yaml.safe_load(f)

es_host = config.get('es', {}).get('host', 'http://localhost:59200')
try:
    resp = requests.get(f"{es_host}/_cluster/health", timeout=5, verify=False)
    print(f"ES 连接 OK: {resp.json().get('cluster_name')}")
except Exception as e:
    print(f"ES 连接失败: {e}")

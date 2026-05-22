#!/usr/bin/env python3
"""测试 ES 连接"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import warnings
warnings.filterwarnings('ignore')
import requests
from commands.utils import load_config

def main():
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config = load_config(os.path.join(script_dir, 'config.yml'))
    es_host = config.get('es', {}).get('host', 'http://localhost:59200')
    
    try:
        r = requests.get(f"{es_host}/_cluster/health", timeout=10, verify=False)
        print(f"[✓] ES 连接成功: {es_host}")
        print(f"    集群状态: {r.json().get('status')}")
    except Exception as e:
        print(f"[✗] ES 连接失败: {e}")

if __name__ == '__main__':
    main()

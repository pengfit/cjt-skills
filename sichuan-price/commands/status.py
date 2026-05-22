#!/usr/bin/env python3
"""查看同步状态"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
store_path = os.path.join(script_dir, '.sichuan_sync_progress.json')

if os.path.exists(store_path):
    with open(store_path) as f:
        data = json.load(f)
    print(f"周期: {data.get('period', '—')}")
    print(f"页码: {data.get('page', 1)}")
else:
    print("无本地进度记录")

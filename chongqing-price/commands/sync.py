#!/usr/bin/env python3
"""同步入口 - 转发给 write_es.py sync 命令"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from commands.write_es import cmd_sync
import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="重庆工程造价材料信息同步")
    parser.add_argument("--reset", action="store_true", help="重置进度，重新开始")
    parser.add_argument("--period", default="2026年01月", help="目标周期")
    parser.add_argument("--run-id", default="", help="指定 run_id")
    parser.add_argument("--tab-id", default="", help="浏览器标签页 ID")
    args = parser.parse_args()
    cmd_sync(args)

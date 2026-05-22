"""工具函数"""
import sys, os, yaml
from typing import Dict, Any

def load_config(path: str) -> Dict[str, Any]:
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    return {}
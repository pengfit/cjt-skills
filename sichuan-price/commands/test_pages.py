#!/usr/bin/env python3
"""测试翻页边界 - 检查实际数据量"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import warnings
warnings.filterwarnings('ignore')
from commands.utils import SiteSession, parse_table

session = SiteSession()

for p in [1, 2, 5, 10, 20, 50]:
    html = session.fetch('2026年03月', p)
    if not html:
        print(f"Page {p}: FAILED")
        continue
    cities, rows = parse_table(html)
    print(f"Page {p}: materials={len(rows)}, cities={len(cities)}, first={rows[0]['breed'] if rows else 'NONE'}, last={rows[-1]['breed'] if rows else 'NONE'}")

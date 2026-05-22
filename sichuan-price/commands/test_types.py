#!/usr/bin/env python3
"""测试价格类型切换"""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import warnings
warnings.filterwarnings('ignore')
import requests

s = requests.Session()
s.headers.update({'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'})

url = 'http://202.61.90.35:8032/pubpages/pricelist.aspx'
resp = s.get(url, timeout=30, verify=False)
resp.encoding = 'utf-8'
html = resp.text

# Check what all form inputs look like
all_inp = re.findall(r'<input[^>]*>', html)
print("=== ALL INPUTS ===")
for inp in all_inp:
    n = re.search(r'name="([^"]*)"', inp)
    t = re.search(r'type="([^"]*)"', inp)
    v = re.search(r'value="([^"]*)"', inp)
    print(f"  name={n.group(1) if n else ''} type={t.group(1) if t else ''} val={v.group(1)[:20] if v else ''}")

# Check all data in the page - especially what "是否含税" values exist
rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
print("\n=== 是否含税 values ===")
is_tax_vals = set()
for row in rows:
    cells = [re.sub(r'<[^>]+>', '', c).strip() for c in re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)]
    cells = [c for c in cells if c]
    if len(cells) >= 4 and cells[0] not in ['名称', '成都市区'] and '天府新区' not in cells[0]:
        is_tax_vals.add(cells[3])
print(is_tax_vals)

# Check how many pages there actually are by looking for any server-side page indicators
page_indicators = re.findall(r'(?:总|共|计|\d+).{0,3}(?:页|记录|条|数据)', html)
print("\nPage indicators:", page_indicators[:5])

# Check the actual table structure - how many city columns
city_row = None
for row in rows:
    cells = [re.sub(r'<[^>]+>', '', c).strip() for c in re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)]
    if '成都市区' in cells[0]:
        city_row = cells
        break
print("\nCity columns:", len(city_row) if city_row else 0)
print("City names:", city_row if city_row else [])

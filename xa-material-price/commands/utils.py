"""工具函数"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
import yaml
import warnings
import requests
from datetime import datetime
from typing import Optional, Dict, Any, List

warnings.filterwarnings('ignore')

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate',
}

COUNTY_CODES = {
    '阎良区': 'YLQU',
    '临潼区': 'LTQU',
    '高陵区': 'GLQU',
    '鄠邑区': 'HYQU',
    '蓝田县': 'LTXU',
    '周至县': 'ZZXU',
}


class SiteSession:
    """ASP.NET 站点 Session，维护 ViewState 实现翻页"""

    def __init__(self, max_retries: int = 5, timeout: int = 60):
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.base_url = 'https://zjj.xa.gov.cn/zxcx/gczj/index.aspx'
        self.max_retries = max_retries
        self.timeout = timeout

    def _extract_form_data(self, html: str) -> Dict[str, str]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        data = {}
        for inp in soup.find_all('input', type='hidden'):
            name = inp.get('name')
            val = inp.get('value', '')
            if name:
                data[name] = val
        return data

    def _do_post(self, url: str, data: Dict[str, str]) -> Optional[str]:
        for attempt in range(self.max_retries):
            try:
                resp = self.session.post(url, data=data, timeout=self.timeout, verify=False)
                resp.encoding = 'utf-8'
                if len(resp.text) < 5000:
                    raise ValueError(f"Bad response: {len(resp.text)}")
                return resp.text
            except Exception as e:
                if attempt < self.max_retries - 1:
                    import time
                    time.sleep(3 * (attempt + 1))
                    continue
                return None
        return None

    def fetch(self, county: str, page: int) -> Optional[str]:
        """抓取指定区县+页码的数据

        每页都用 GET 初始化，然后 POST 提交 ddl_qdm + rptPager_input
        支持超时重试
        """
        code = COUNTY_CODES.get(county, county)
        url = f"{self.base_url}?page={page}&qdm={code}"

        for attempt in range(self.max_retries):
            try:
                # 每次都先 GET 获取最新的 __VIEWSTATE 等隐藏字段
                resp = self.session.get(url, timeout=self.timeout, verify=False)
                resp.encoding = 'utf-8'
                html = resp.text
                if len(html) < 5000:
                    return None

                form_data = self._extract_form_data(html)
                form_data['ddl_qdm'] = code
                form_data['rptPager_input'] = str(page)

                return self._do_post(url, form_data)
            except Exception:
                if attempt < self.max_retries - 1:
                    import time
                    time.sleep(3 * (attempt + 1))
                    continue
                return None
        return None


def parse_page_date(html_text: str) -> Optional[str]:
    m = re.search(r'更新时间[：:]\s*(\d{4}-\d{2}-\d{2})', html_text)
    return m.group(1) if m else None


def parse_county(html_text: str) -> Optional[str]:
    m = re.search(r'<span id="lab_qx">([^<]+)</span>', html_text)
    return m.group(1) if m else None


def parse_total_records(html_text: str) -> int:
    m = re.search(r'共查询到<span[^>]*id="lblListCount"[^>]*>(\d+)</span>个材料信息', html_text)
    return int(m.group(1)) if m else 0


def parse_table_rows(html_text: str) -> List[Dict[str, Any]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html_text, 'html.parser')
    tables = soup.find_all('table')
    if len(tables) < 2:
        return []

    rows = []
    for tr in tables[1].find_all('tr'):
        cells = [td.get_text(strip=True) for td in tr.find_all('td')]
        if len(cells) < 6 or not re.match(r'^\d+$', cells[0]):
            continue

        price = None
        if cells[4] and cells[4] not in ('/', '—', ''):
            try:
                price = float(cells[4])
            except ValueError:
                pass

        tax_price = None
        if cells[5] and cells[5] not in ('/', '—', ''):
            try:
                tax_price = float(cells[5])
            except ValueError:
                pass

        rows.append({
            'code': cells[0],
            'breed': cells[1],
            'spec': cells[2],
            'unit': cells[3],
            'price': price,
            'tax_price': tax_price,
        })
    return rows


def load_config(config_path: str) -> Dict[str, Any]:
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def get_last_update_date(es_host: str, es_index: str) -> Optional[str]:
    try:
        url = f"{es_host}/{es_index}/_search"
        body = {"size": 1, "sort": [{"update_date": "desc"}], "_source": ["update_date"]}
        resp = requests.post(url, json=body, timeout=10, verify=False)
        hits = resp.json().get('hits', {}).get('hits', [])
        if hits:
            return hits[0]['_source'].get('update_date')
    except Exception:
        pass
    return None



def get_last_update_date_by_county(es_host: str, es_index: str, county: str) -> Optional[str]:
    """返回指定区县的最新 update_date（按 update_date desc 取第一条）"""
    try:
        url = f"{es_host}/{es_index}/_search"
        body = {
            "size": 1,
            "query": {"term": {"county": county}},
            "sort": [{"update_date": "desc"}],
            "_source": ["update_date"]
        }
        resp = requests.post(url, json=body, timeout=10, verify=False)
        hits = resp.json().get('hits', {}).get('hits', [])
        if hits:
            return hits[0]['_source'].get('update_date')
    except Exception:
        pass
    return None


def spot_check_county(es_host: str, es_index: str, county: str, site_rows: List[Dict]) -> dict:
    """
    增量抽检：对比 ES 中该区县按入库时间正序的前10条记录 与 网站首页记录。
    匹配键：breed + spec + unit + price + tax_price（5字段完全一致才视为同一条记录）。
    site_rows 为 parse_table_rows(html) 的返回值（breed/spec/unit/price/tax_price 已解析）。

    返回:
        consistent: True/False
        mismatches: [ {"es_breed": ..., "es_spec": ..., "es_unit": ..., "es_price": ...,
                       "es_tax_price": ..., "es_update": ..., "reason": ...}, ... ]
    """
    try:
        url = f"{es_host}/{es_index}/_search"
        body = {
            "size": 10,
            "query": {"term": {"county": county}},
            "sort": [{"create_time": "asc"}],
            "_source": ["breed", "spec", "unit", "update_date", "price", "tax_price"]
        }
        resp = requests.post(url, json=body, timeout=10, verify=False)
        hits = resp.json().get('hits', {}).get('hits', [])
    except Exception:
        return {"consistent": True, "mismatches": []}

    def row_key(r):
        return (
            str(r.get('breed', '')).strip(),
            str(r.get('spec', '')).strip(),
            str(r.get('unit', '')).strip(),
            str(r.get('price', '')).strip(),
            str(r.get('tax_price', '')).strip(),
        )

    mismatches = []
    for h in hits:
        src = h['_source']
        es_breed = src.get('breed', '')
        es_spec = src.get('spec', '')
        es_unit = src.get('unit', '')
        es_price = src.get('price', '')
        es_tax_price = src.get('tax_price', '')
        es_update = src.get('update_date', '')

        key = row_key(src)
        found = any(row_key(row) == key for row in site_rows)

        if not found:
            mismatches.append({
                "es_breed": es_breed,
                "es_spec": es_spec,
                "es_unit": es_unit,
                "es_price": es_price,
                "es_tax_price": es_tax_price,
                "es_update": es_update,
                "reason": "ES记录未出现在网站首页"
            })

    return {
        "consistent": len(mismatches) == 0,
        "mismatches": mismatches,
    }

def save_sync_time(config_path: str, update_date: str):
    config = load_config(config_path)
    config['sync']['last_update_date'] = update_date
    with open(config_path, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)


def ensure_index(es_host: str, es_index: str):
    try:
        resp = requests.head(f"{es_host}/{es_index}", timeout=10, verify=False)
        if resp.status_code == 200:
            return
    except Exception:
        pass

    mapping = {
        "mappings": {
            "properties": {
                "code":        {"type": "keyword"},
                "breed":       {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
                "spec":        {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
                "unit":        {"type": "keyword"},
                "price":       {"type": "float"},
                "tax_price":   {"type": "float"},
                "county":      {"type": "keyword"},
                "province":    {"type": "keyword"},
                "city":        {"type": "keyword"},
                "update_date": {"type": "date", "format": "yyyy-MM-dd"},
                "create_time": {"type": "date", "format": "yyyy-MM-dd HH:mm:ss"}
            }
        }
    }

    try:
        resp = requests.put(f"{es_host}/{es_index}", json=mapping, timeout=10, verify=False)
        if resp.status_code in (200, 201):
            print(f"  [✓] 创建索引: {es_index}")
    except Exception as e:
        print(f"  [!] 创建索引异常: {e}")


def format_table(headers: List[str], rows: List[List[str]]) -> str:
    if not rows:
        return ""
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(str(cell)))
    lines = []
    lines.append(" | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)))
    lines.append("-" * len(lines[0]))
    for row in rows:
        lines.append(" | ".join(str(row[i]).ljust(col_widths[i]) for i in range(len(row))))
    return "\n".join(lines)
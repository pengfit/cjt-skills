"""工具函数"""
def _resolve_etl_root():
    """解析 gov-price-etl 项目根路径。

    优先级：
      1) 环境变量 GOV_PRICE_ETL_ROOT（部署/调试可显式覆盖）
      2) 自动反推：从本文件路径向上找 'gov-price-etl' 同级目录，
         不依赖硬编码的 workspace 名 / 目录深度。
      3) 兜底 fallback（cjt 子目录布局），让上层 log warning，不抛异常。
    """
    import os
    from pathlib import Path
    env = os.environ.get("GOV_PRICE_ETL_ROOT")
    if env and os.path.isdir(env):
        return env
    p = Path(__file__).resolve().parent
    for _ in range(6):
        candidate = p / "gov-price-etl"
        if candidate.is_dir():
            return str(candidate)
        p = p.parent
    return str(Path.home() / ".openclaw" / "workspace" / "cjt" / "skills" / "gov-price-etl")


import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
import yaml
import warnings
import requests
from datetime import datetime
from typing import Optional, Dict, Any, List
# 复用 gov_price_etl 通用层（ODS mapping 标准化）
_ETL_PROJECT_ROOT = _resolve_etl_root()
if os.path.isdir(_ETL_PROJECT_ROOT) and _ETL_PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _ETL_PROJECT_ROOT)


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


def normalize_period(period: str) -> str:
    """标准化周期字符串为 YYYY-MM 格式

    支持输入:
        '2026-01' / '2026-1' / '2026年01月' / '2026年1月' / '2026/01'
    """
    period = period.strip()
    m = re.match(r'^(\d{4})[-/年](\d{1,2})月?$', period)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    return period


def period_to_label(period: str) -> str:
    """把 YYYY-MM 转成源站 name 格式 'YYYY年MM月造价信息表'"""
    y, m = period.split('-')
    return f"{y}年{int(m):02d}月造价信息表"


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

    def fetch(self, county: str, page: int, gkbh: Optional[str] = None) -> Optional[str]:
        """抓取指定区县+页码的数据

        每页都用 GET 初始化，然后 POST 提交 ddl_qdm + rptPager_input
        gkbh: 周期 ID（来自 Handler.ashx），传了则按月筛选
        支持超时重试
        """
        code = COUNTY_CODES.get(county, county)
        url = f"{self.base_url}?page={page}&qdm={code}"
        if gkbh:
            url += f"&gkbh={gkbh}"

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
                if gkbh:
                    form_data['gkbh'] = gkbh

                return self._do_post(url, form_data)
            except Exception:
                if attempt < self.max_retries - 1:
                    import time
                    time.sleep(3 * (attempt + 1))
                    continue
                return None
        return None

    def list_periods(self, county: str, year: int) -> List[Dict[str, str]]:
        """拿指定区县某年的所有月份（造价信息表）列表

        Returns:
            [{'id': '0000000595', 'name': '2026年01月造价信息表', 'period': '2026-01'}, ...]
        """
        import json as _json
        code = COUNTY_CODES.get(county, county)
        url = "https://zjj.xa.gov.cn/zxcx/gczj/Handler.ashx"
        params = {'year': str(year), 'qymc': county, 'type': '1', 'version': '2'}
        for attempt in range(self.max_retries):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout, verify=False)
                resp.encoding = 'utf-8'
                data = _json.loads(resp.text)
                # 解析 name: "2026年01月造价信息表" → period: "2026-01"
                out = []
                for item in data:
                    name = item.get('name', '')
                    m = re.search(r'(\d{4})年(\d{2})月', name)
                    if m:
                        period = f"{m.group(1)}-{m.group(2)}"
                    else:
                        period = ''
                    out.append({
                        'id': item.get('id', ''),
                        'name': name,
                        'period': period,
                    })
                return out
            except Exception:
                if attempt < self.max_retries - 1:
                    import time
                    time.sleep(2 * (attempt + 1))
                    continue
                return []
        return []


def list_all_years(county: str, session: Optional['SiteSession'] = None) -> List[int]:
    """探测指定区县有哪些年有数据，从 2024 往前倒推

    Returns: [2026, 2025, 2024, ...] 有数据的年份（倒序）
    """
    sess = session or SiteSession(max_retries=2, timeout=15)
    years = []
    # 西安源站 2024 年开始有数据；从当前年往前探测
    now = datetime.now()
    for y in range(now.year, 2023, -1):
        periods = sess.list_periods(county, y)
        if periods:
            years.append(y)
    return years


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
    """确保 ES 索引存在，套用 mapping（如果不存在）

    v0.5 (2026-07-02) ：委托到 gov_price_etl.indexer.ensure_ods_index（requests 风格）。
    新字段（区间价 price_min/max/range/is_range 等）自动生效。
        city_extension=gkbh
    """
    from gov_price_etl.mappings import build_ods_mapping
    from gov_price_etl.indexer import ensure_ods_index
    ok = ensure_ods_index(
        es_host,
        es_index,
        city_extension={
            "gkbh": {'type': 'keyword'},
        },
    )
    if ok:
        print(f"  [✓] 创建索引: {es_index}")




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
"""四川工程造价信息 - SiteSession 和解析函数"""
def _resolve_etl_root():
    """解析 gov-price-etl 项目根路径。

    优先级：
      1) 环境变量 GOV_PRICE_ETL_ROOT（部署/调试可显式覆盖）
      2) 自动反推：从本文件路径向上找 'gov-price-etl' 同级目录，
         不依赖硬编码的 workspace 名 / 目录深度。
      3) 兜底扫描：~/.openclaw/workspace/*/skills/gov-price-etl,
         不预设 workspace 名。
      4) 仍找不到：抛错提示用户设环境变量。绝不默默返回错误路径。
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
    workspace_root = Path.home() / ".openclaw" / "workspace"
    if workspace_root.is_dir():
        for ws in workspace_root.iterdir():
            candidate = ws / "skills" / "gov-price-etl"
            if candidate.is_dir():
                return str(candidate)
    raise FileNotFoundError(
        "找不到 gov-price-etl 项目根。"
        "请设置环境变量 GOV_PRICE_ETL_ROOT 指向项目根，"
        "或确认 ETL 已部署在 <workspace>/skills/gov-price-etl。"
    )


import sys, os, re, yaml, warnings, requests
from datetime import datetime
from typing import Optional, Dict, Any, List
from bs4 import BeautifulSoup
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

# 四川21个地级市/自治州代码
AREA_CODES = {
    '川A': '成都市', '川B': '绵阳市', '川C': '自贡市', '川D': '攀枝花市',
    '川E': '泸州市', '川F': '德阳市', '川H': '广元市', '川J': '遂宁市',
    '川K': '内江市', '川L': '乐山市', '川M': '资阳市', '川Q': '宜宾市',
    '川R': '南充市', '川S': '达州市', '川T': '雅安市', '川U': '阿坝州',
    '川V': '甘孜州', '川W': '凉山州', '川X': '广安市', '川Y': '巴中市',
    '川Z': '眉山市',
}


class SiteSession:
    """ASP.NET 站点 Session，维护 ViewState，支持分页"""

    def __init__(self, max_retries: int = 5, timeout: int = 60):
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.base_url = 'http://202.61.90.35:8032/pubpages/pricelist.aspx'
        self.max_retries = max_retries
        self.timeout = timeout
        self.vs = None
        self.vsg = None
        self._fetch_init()

    def _fetch_init(self):
        resp = self.session.get(self.base_url, timeout=self.timeout, verify=False)
        resp.encoding = 'utf-8'
        html = resp.text
        self._update_vs(html)

    def _update_vs(self, html: str):
        vs_m = re.search(r'<input[^>]*name="__VIEWSTATE"[^>]*value="([^"]*)"', html)
        vsg_m = re.search(r'<input[^>]*name="__VIEWSTATEGENERATOR"[^>]*value="([^"]*)"', html)
        if vs_m: self.vs = vs_m.group(1)
        if vsg_m: self.vsg = vsg_m.group(1)

    def _do_post(self, data: Dict[str, str]) -> Optional[str]:
        for attempt in range(self.max_retries):
            try:
                resp = self.session.post(self.base_url, data=data, timeout=self.timeout, verify=False)
                resp.encoding = 'utf-8'
                if len(resp.text) < 1000:
                    raise ValueError(f"Bad response: {len(resp.text)}")
                return resp.text
            except Exception:
                if attempt < self.max_retries - 1:
                    import time; time.sleep(2 * (attempt + 1))
        return None

    def fetch(self, area: str, period: str, page: int) -> tuple:
        """抓取指定地区+周期+页码的数据。
        返回 (html, area_name, period_name)"""
        data = {
            '__VIEWSTATE': self.vs or '',
            '__VIEWSTATEGENERATOR': self.vsg or '',
            'keyword': '', 'pricetype': '4', 'clscode': '',
            'area': area, 'period': period,
            'pageIndex': str(page), 'pageSize': '25'
        }
        html = self._do_post(data)
        if html:
            self._update_vs(html)
        # 从页面提取真实周期名称（如 "2026年03月"）
        m = re.search(r'<input[^>]*id="txtPeriod"[^>]*value="([^"]*)"', html)
        period_name = m.group(1) if m else period
        return html, AREA_CODES.get(area, area), period_name


def parse_page(html: str) -> tuple:
    """
    解析页面（使用 BeautifulSoup 正确提取 <a> 内的价格文本）。
    返回: (city_headers: List[str], material_rows: List[Dict],
           total: int, page_size: int, page_index: int)
    """
    soup = BeautifulSoup(html, 'html.parser')
    table = soup.find('table', id='tbPrice')
    if not table:
        return [], [], 0, 25, 1

    all_rows = table.find_all('tr')
    if len(all_rows) < 3:
        return [], [], 0, 25, 1

    # Row 1: 城市/区县列标题
    city_headers = [td.get_text(strip=True) for td in all_rows[1].find_all('td')]

    # Row 2+: 材料数据
    material_rows = []
    for tr in all_rows[2:]:
        cells = [td.get_text(strip=True) for td in tr.find_all('td')]
        if not cells or cells[0] in ('名称',) or len(cells) < 5:
            continue

        breed = cells[0]
        spec = cells[1] if len(cells) > 1 else ''
        unit = cells[2] if len(cells) > 2 else ''
        is_tax = cells[3] if len(cells) > 3 else ''
        price_str = cells[4] if len(cells) > 4 else ''

        # 主价格（列5，index 4）
        main_price = 0.0
        if '￥' in price_str:
            try:
                main_price = float(re.sub(r'[￥,\s]', '', price_str))
            except Exception:
                pass

        # 各城市价格（列6+，index 5+）
        city_prices = cells[5:] if len(cells) > 5 else []

        material_rows.append({
            'breed': breed, 'spec': spec, 'unit': unit,
            'is_tax': is_tax, 'price': main_price,
            'city_prices': city_prices,
        })

    # 分页信息
    pager_div = soup.find('div', class_='pager')
    total = 0; page_size = 25; page_index = 1
    if pager_div:
        m = re.search(r'pageindex="(\d+)"', str(pager_div))
        s = re.search(r'pagesize="(\d+)"', str(pager_div))
        t = re.search(r'total="(\d+)"', str(pager_div))
        if m: page_index = int(m.group(1))
        if s: page_size = int(s.group(1))
        if t: total = int(t.group(1))

    return city_headers, material_rows, total, page_size, page_index


def _parse_price(s: str) -> float:
    try:
        return float(re.sub(r'[￥,，元\-\s]', '', s))
    except Exception:
        return 0.0


def ensure_index(es_host: str, es_index: str):
    """确保 ES 索引存在，套用 mapping（如果不存在）

    v0.5 (2026-07-02) ：委托到 gov_price_etl.indexer.ensure_ods_index（requests 风格）。
    新字段（区间价 price_min/max/range/is_range 等）自动生效。
        city_extension=None（使用通用模板）
    """
    from gov_price_etl.indexer import ensure_ods_index
    ensure_ods_index(es_host, es_index)
    print(f"  [✓] 创建索引: {es_index}")




def ensure_progress_index(es_host: str, idx: str):
    """确保同步进度索引存在

    v0.6 (2026-07-02) ：委托到 gov_price_etl.indexer.ensure_progress_index。
    单点维护 36 个进度字段。

    _id 规则（v0.6 标准化建议）：
        区县进度：f"{run_id}__{source}__{county}__{period}"
        run 汇总：f"{run_id}__summary"
        spot check：f"{run_id}__spot__{county}"
    """
    from gov_price_etl.indexer import ensure_progress_index as _ensure
    if _ensure(es_host, idx):
        print(f"  [✓] 创建 progress: {idx}")



def load_config(path: str) -> Dict[str, Any]:
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    return {}


def get_all_periods(session=None) -> List[Dict]:
    """从网站 API 获取所有可用周期列表"""
    close_session = False
    if session is None:
        session = requests.Session()
        session.headers.update(DEFAULT_HEADERS)
        close_session = True
    try:
        r = session.get(
            'http://202.61.90.35:8032/handler/Pubservices.ashx?ActionName=HomeAction&MethodName=GetAllPublishPeriodList',
            timeout=30, verify=False
        )
        return r.json()
    finally:
        if close_session:
            session.close()


def get_latest_period() -> tuple:
    """获取最新一个周期，返回 (period_name, period_guid)"""
    periods = get_all_periods()
    active = [p for p in periods if p.get('State') == 1]
    latest = max(active, key=lambda x: x.get('PeriodNo', 0))
    return latest['PeriodName'], latest['Guid']
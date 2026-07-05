"""济南工程造价材料信息 - SiteSession 和解析函数"""
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


import sys, os, re, yaml, warnings, requests, json
from datetime import datetime
from typing import Optional, Dict, Any, List
from playwright.sync_api import sync_playwright
# 复用 gov_price_etl 通用层（ODS mapping 标准化）
_ETL_PROJECT_ROOT = _resolve_etl_root()
if os.path.isdir(_ETL_PROJECT_ROOT) and _ETL_PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _ETL_PROJECT_ROOT)


warnings.filterwarnings('ignore')

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate',
    'Content-Type': 'application/json',
}


class JinAnSiteSession:
    """济南材料价格网站 API Session，维护 token，支持分页"""

    def __init__(self, base_url: str = 'http://jnxxj.jngczjxh.com:5020', timeout: int = 60):
        self.base_url = base_url.rstrip('/')
        self.api_base = f"{self.base_url}/cj/api/build"
        self.timeout = timeout
        self.token = None
        self._init_session()

    def _init_session(self):
        """使用 Playwright 初始化 Session，获取 token"""
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, channel='chromium')
                page = browser.new_page()

                # 访问主页触发 token 设置
                page.goto(f"{self.base_url}/cj/", timeout=30000, wait_until='domcontentloaded')
                page.wait_for_timeout(3000)

                # 从 localStorage 获取 token
                try:
                    self.token = page.evaluate("() => localStorage.getItem('token') || localStorage.getItem('TOKEN')")
                except Exception:
                    self.token = None

                if not self.token:
                    # 触发完整初始化
                    page.goto(f"{self.base_url}/cj/material-wave", timeout=30000, wait_until='domcontentloaded')
                    page.wait_for_timeout(5000)
                    try:
                        self.token = page.evaluate("() => localStorage.getItem('token') || localStorage.getItem('TOKEN')")
                    except Exception:
                        self.token = None

                browser.close()
        except Exception as e:
            print(f"[!] Playwright 初始化失败: {e}")
            self.token = None

    def _headers(self) -> Dict[str, str]:
        headers = dict(DEFAULT_HEADERS)
        if self.token:
            headers['token'] = self.token
        return headers

    def fetch(self, period_id: str, catalogue_id: str, page: int = 1, size: int = 100, data_type: str = "2") -> Optional[Dict]:
        """抓取指定周期+分类+页码的数据"""
        url = f"{self.api_base}/material/searchPublishPriceMaterialPage"
        body = {
            "productName": "",
            "year": "",
            "periodId": str(period_id),
            "code": "",
            "searchName": "",
            "searchFeatures": "",
            "current": page,
            "size": size,
            "catalogueId": str(catalogue_id),
            "dataType": data_type,
            "isPreview": True
        }
        try:
            resp = requests.post(url, data=json.dumps(body), headers=self._headers(), timeout=self.timeout, verify=False)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('code') == 0 and data.get('successFul'):
                    return data.get('data', {})
        except Exception as e:
            print(f"[!] 请求失败 (页{page}): {e}")
        return None

    def get_last_period(self) -> tuple:
        """获取最新周期，返回 (period_name, period_id)"""
        url = f"{self.api_base}/period/getLastPeriodId"
        try:
            resp = requests.get(url, headers=self._headers(), timeout=self.timeout, verify=False)
            data = resp.json()
            if data.get('code') == 0:
                period_id = data.get('data')
                # 获取周期名称
                period_name = self._get_period_name(period_id)
                return period_name, str(period_id)
        except Exception as e:
            print(f"[!] 获取最新周期失败: {e}")
        return '', ''

    def _get_period_name(self, period_id: str) -> str:
        """根据 periodId 获取周期名称"""
        url = f"{self.api_base}/period/selectPeriodList?periodId={period_id}"
        try:
            resp = requests.get(url, headers=self._headers(), timeout=self.timeout, verify=False)
            data = resp.json()
            if data.get('code') == 0:
                for p in data.get('data', []):
                    if str(p.get('id')) == str(period_id):
                        return p.get('periodName', '')
        except Exception:
            pass
        return ''

    def get_all_periods(self) -> List[Dict]:
        """获取所有可用周期列表"""
        url = f"{self.api_base}/period/getLastPeriodId"
        try:
            resp = requests.get(url, headers=self._headers(), timeout=self.timeout, verify=False)
            last_id = resp.json().get('data') if resp.status_code == 200 else None
            if not last_id:
                return []

            # 获取完整周期列表
            list_url = f"{self.api_base}/period/selectPeriodList?periodId={last_id}"
            resp2 = requests.get(list_url, headers=self._headers(), timeout=self.timeout, verify=False)
            data = resp2.json()
            if data.get('code') == 0:
                return data.get('data', [])
        except Exception as e:
            print(f"[!] 获取周期列表失败: {e}")
        return []

    def get_catalogue_tree(self, data_type: str = "2") -> List[Dict]:
        """获取分类目录树"""
        url = f"{self.api_base}/catalogue/catalogueTree?dataType={data_type}"
        try:
            resp = requests.get(url, headers=self._headers(), timeout=self.timeout, verify=False)
            data = resp.json()
            if data.get('code') == 0:
                return data.get('data', [])
        except Exception as e:
            print(f"[!] 获取分类目录失败: {e}")
        return []

    def get_all_catalogue_ids(self, data_type: str = "2") -> List[str]:
        """从分类目录中提取所有叶子类目 ID"""
        tree = self.get_catalogue_tree(data_type)
        ids = []

        def flatten_nodes(nodes):
            for node in nodes:
                is_leaf = node.get('isLeaf', 0)
                node_id = str(node.get('id', ''))
                if is_leaf == 1 and node_id:
                    ids.append(node_id)
                children = node.get('childrenCatalogue', [])
                if children:
                    flatten_nodes(children)

        flatten_nodes(tree)
        return ids

    def find_catalogue_name_by_id(self, cat_id: str, data_type: str = "2") -> str:
        """根据 catalogueId 递归查找分类名称"""
        tree = self.get_catalogue_tree(data_type)
        target_id = str(cat_id)

        def search(nodes):
            for node in nodes:
                if str(node.get('id', '')) == target_id:
                    return node.get('name', '')
                children = node.get('childrenCatalogue', [])
                if children:
                    result = search(children)
                    if result is not None:
                        return result
            return None

        return search(tree) or ''


def ensure_index(es_host: str, es_index: str):
    """确保 ES 索引存在，套用 mapping（如果不存在）

    v0.5 (2026-07-02) ：委托到 gov_price_etl.indexer.ensure_ods_index（requests 风格）。
    新字段（区间价 price_min/max/range/is_range 等）自动生效。
        city_extension=catalogue, catalogue_name
    """
    from gov_price_etl.mappings import build_ods_mapping
    from gov_price_etl.indexer import ensure_ods_index
    ok = ensure_ods_index(
        es_host,
        es_index,
        city_extension={
            "catalogue": {'type': 'keyword'},
            "catalogue_name": {'type': 'keyword'},
        },
    )
    if ok:
        print(f"  [✓] 创建索引: {es_index}")




def ensure_progress_index(es_host: str, idx: str, city_extension: dict = None):
    """确保同步进度索引存在

    v0.6 (2026-07-02) ：委托到 gov_price_etl.indexer.ensure_progress_index。
    单点维护 36 个进度字段。

    _id 规则（v0.6 标准化建议）：
        区县进度：f"{run_id}__{source}__{county}__{period}"
        run 汇总：f"{run_id}__summary"
        spot check：f"{run_id}__spot__{county}"

    v0.1 (2026-07-03) ：透传 city_extension 以支持城市特化字段（如 period_id）。
    """
    from gov_price_etl.indexer import ensure_progress_index as _ensure
    if _ensure(es_host, idx, city_extension=city_extension):
        print(f"  [✓] 创建 progress: {idx}")



def load_config(path: str) -> Dict[str, Any]:
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    return {}


def ensure_catalogue_index(es_host: str, idx: str):
    """确保分类目录索引存在"""
    try:
        resp = requests.head(f"{es_host}/{idx}", timeout=10, verify=False)
        if resp.status_code == 200:
            return
    except Exception:
        pass
    mapping = {
        "mappings": {
            "properties": {
                "id":           {"type": "keyword"},
                "name":          {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
                "code":          {"type": "keyword"},
                "parentId":      {"type": "keyword"},
                "isLeaf":        {"type": "integer"},
                "grade":         {"type": "integer"},
                "dataType":      {"type": "keyword"},
                "period":        {"type": "keyword"},
                "period_id":     {"type": "keyword"},
                "province":      {"type": "keyword"},
                "city":          {"type": "keyword"},
                "county":        {"type": "keyword"},
                "sort":          {"type": "integer"},
                "create_time":   {"type": "date", "format": "yyyy-MM-dd HH:mm:ss||yyyy-MM-dd||strict_date_optional_time"},
            }
        }
    }
    requests.put(f"{es_host}/{idx}", json=mapping, timeout=30, verify=False)


def _flatten_catalogue_tree(nodes, period, period_id, docs):
    """递归扁平化分类目录树，收集所有节点"""
    for node in nodes:
        docs.append({
            '_id': str(node.get('id', '')),
            'id': str(node.get('id', '')),
            'name': node.get('name', ''),
            'code': node.get('code', ''),
            'parentId': str(node.get('parentId', '0')),
            'isLeaf': node.get('isLeaf', 0),
            'grade': node.get('grade', 0),
            'dataType': node.get('dataType', ''),
            'sort': node.get('sort', 0),
            'period': period,
            'period_id': period_id,
            'province': '山东',
            'city': '济南',
            'county': '济南',
            'create_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        })
        children = node.get('childrenCatalogue', [])
        if children:
            _flatten_catalogue_tree(children, period, period_id, docs)


def sync_catalogue_to_es(session: JinAnSiteSession, es_host: str, es_index: str, period: str, period_id: str, data_type: str = "2", dry_run: bool = False) -> int:
    """把分类目录树同步到 ES，返回写入文档数"""
    ensure_catalogue_index(es_host, es_index)
    tree = session.get_catalogue_tree(data_type)
    docs = []
    _flatten_catalogue_tree(tree, period, period_id, docs)
    if not docs:
        return 0
    if dry_run:
        print(f"  [CAT] 分类目录 {len(docs)} 个（预览模式）")
        return len(docs)
    bulk = ''
    for doc in docs:
        doc_id = doc.pop('_id')
        bulk += json.dumps({"index": {"_index": es_index, "_id": doc_id}}, ensure_ascii=False) + '\n'
        bulk += json.dumps(doc, ensure_ascii=False) + '\n'
    try:
        resp = requests.post(f"{es_host}/_bulk",
            data=bulk.encode('utf-8'),
            headers={"Content-Type": "application/x-ndjson"},
            timeout=30, verify=False)
        if resp.status_code in (200, 201):
            items = resp.json().get('items', [])
            return sum(1 for it in items if it.get('index', {}).get('result') in ('created', 'updated'))
    except Exception as e:
        print(f"  [!] 分类目录写入失败: {e}")
    return 0

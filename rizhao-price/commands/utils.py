"""utils.py - rizhao 共用工具（v1.0 SyncRunner 化, 2026-07-03）

v1.0 调整：
- ensure_index / ensure_progress_index 已委托到 gov_price_etl.indexer（v0.5/v0.6）
- mapping 自动包含 period_start / period_end / period_days 字段（v1.0 新增）
- 新增 parse_period_window()（位于 rizhao_collector.py，本文件只保留通用工具）

复用：
- 从 v0 utils 继承 TAB_TYPES / AREA_CODES / load_config / doc_id 等
- ensure_index / ensure_progress_index 委托到 ETL 公共层（避免重复维护）
"""
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


import sys, os, re, yaml, json, subprocess, hashlib, warnings, requests
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

# ── ETL 公共依赖 ──
_ETL_PROJECT_ROOT = _resolve_etl_root()
if os.path.isdir(_ETL_PROJECT_ROOT) and _ETL_PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _ETL_PROJECT_ROOT)


warnings.filterwarnings('ignore')

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}

# 日照市辖区县（供 tab_type=3 区县材料分类使用）
AREA_CODES = {
    '001001': '日照市辖区',
    '001002': '东港区',
    '001003': '岚山区',
    '001004': '五莲县',
    '001005': '莒县',
}

# 三个类别
TAB_TYPES = {
    '1': '建设工程材料',
    '2': '园林绿化苗木',
    '3': '区县建设工程材料',
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CHROME_PATH = '/Users/pengfit/Library/Caches/ms-playwright/chromium-1217/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'


def _run_playwright(cmd: str, *args) -> Dict:
    """调用 playwright fetch_data.js，返回解析后的 JSON 数据"""
    js_path = os.path.join(SCRIPT_DIR, 'fetch_data.js')
    proc = subprocess.run(
        ['node', js_path, cmd] + list(args),
        capture_output=True, text=True,
        cwd=SCRIPT_DIR,
        timeout=600,
        env={**os.environ, 'PATH': os.environ.get('PATH', '')}
    )
    if proc.returncode != 0:
        raise RuntimeError(f"playwright failed: {proc.stderr}")
    return json.loads(proc.stdout)


def get_metadata() -> Dict:
    """获取站点元数据：tabs 和当前期数"""
    return _run_playwright('metadata')


def fetch_page(tab_type: str, page: int, page_size: int = 10) -> Dict:
    """抓取指定类别+页码的数据（兼容旧调用）"""
    return _run_playwright('fetch', tab_type, str(1), str(200))


class BrowserSession:
    """基于 Playwright 的浏览器会话，用于获取材价数据（兼容旧版）"""

    def __init__(self, tab_type: str = '1', max_retries: int = 3):
        self.tab_type = tab_type
        self.max_retries = max_retries
        self.metadata = None
        self._fetch_metadata()

    def _fetch_metadata(self):
        try:
            self.metadata = get_metadata()
        except Exception:
            self.metadata = {'tabs': [], 'periods': ''}

    def get_current_period(self) -> str:
        if self.metadata:
            return self.metadata.get('periods', '')
        return datetime.now().strftime('%Y-%m')

    def get_tabs(self) -> List[Dict]:
        if self.metadata:
            return self.metadata.get('tabs', [])
        return []

    def get_data(self, max_pages: int = 200) -> Dict:
        """获取全部数据（自动翻页）"""
        return _run_playwright('fetch', self.tab_type, str(max_pages))

    def get_total_count(self) -> int:
        data = self.get_data(max_pages=1)
        return data.get('totalCount', 0)


def parse_data(data: Dict) -> Tuple[List[Dict], int, str]:
    """解析 fetch_data 输出（兼容旧版）"""
    rows = data.get('rows', [])
    total = data.get('totalCount', 0)
    periods = data.get('periods', '')
    return rows, total, periods


def doc_id(breed: str, spec: str, unit: str, period: str, price: float, city: str, county: str) -> str:
    """幂等 _id = MD5(breed+spec+unit+period+price+city+county)。"""
    raw = f"{breed}_{spec}_{unit}_{period}_{price}_{city}_{county}"
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


def ensure_index(es_host: str, es_index: str):
    """确保 ODS 索引存在（套用 ETL 标准 mapping，含 period_* 字段）。

    v1.0 (2026-07-03) ：委托到 gov_price_etl.indexer.ensure_ods_index。
    之前 v0 自维护 mapping，v1.0 改用 ETL 共享模板（含 period_start/end/days）。
    """
    from gov_price_etl.indexer import ensure_ods_index as _ensure
    if _ensure(es_host, es_index):
        print(f"  [✓] 创建索引: {es_index}")


def ensure_progress_index(es_host: str, idx: str):
    """确保同步进度索引存在。

    v1.0 (2026-07-03) ：委托到 gov_price_etl.indexer.ensure_progress_index。
    单点维护 36 个进度字段（含 period_start/end/days）。
    """
    from gov_price_etl.indexer import ensure_progress_index as _ensure
    if _ensure(es_host, idx):
        print(f"  [✓] 创建 progress: {idx}")


def load_config(path: str) -> Dict[str, Any]:
    """加载 YAML 配置"""
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    return {}
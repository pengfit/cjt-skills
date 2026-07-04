"""威海工程造价信息采集 - 工具函数"""
import calendar
import re
from datetime import date

import os
import sys

import requests

import yaml

# v0.7 (2026-07-02) P1 抽取：工具函数委托到 gov_price_etl.collectors
sys.path.insert(0, '/Users/pengfit/.openclaw/workspace/skills/gov-price-etl')
from gov_price_etl.collectors import ( get_es_client, get_s3_client, ensure_bucket,
    upload_to_minio, minio_object_url, fetch_html, download_file,
)

PERIOD_KEYWORDS = ['主要工程建设材料信息价', '部分工程建设材料指导价格']


def is_price_entry(title: str) -> bool:
    """判断是否为价目相关通知（参考 sync.py 中 _is_price_entry 抽出）"""
    return any(kw in (title or '') for kw in PERIOD_KEYWORDS)


def quarter_period_to_dates(period: str):
    """威海季度 period → (period_start, period_end, period_days)

    支持格式：
      '2026.1-3月'    → ('2026-01-01', '2026-03-31', 90)
      '2026.4-6月'    → ('2026-04-01', '2026-06-30', 91)
      '2026.7-9月'    → ('2026-07-01', '2026-09-30', 92)
      '2026.10-12月'  → ('2026-10-01', '2026-12-31', 92)
      '2026.5月'      → ('2026-05-01', '2026-05-31', 31)  # 单月也支持（2025 之前可能用）

    解析失败返回 (None, None, None)。
    """
    if not period:
        return None, None, None
    # 跨月区间 YYYY.M1-M2月
    m = re.match(r'(\d{4})\.(\d{1,2})-(\d{1,2})月$', period)
    if m:
        year, m1, m2 = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            last_day = calendar.monthrange(year, m2)[1]
        except Exception:
            return None, None, None
        start = date(year, m1, 1)
        end = date(year, m2, last_day)
        return start.isoformat(), end.isoformat(), (end - start).days + 1
    # 单月 YYYY.M月
    m = re.match(r'(\d{4})\.(\d{1,2})月$', period)
    if m:
        year, m1 = int(m.group(1)), int(m.group(2))
        try:
            last_day = calendar.monthrange(year, m1)[1]
        except Exception:
            return None, None, None
        start = date(year, m1, 1)
        end = date(year, m1, last_day)
        return start.isoformat(), end.isoformat(), (end - start).days + 1
    return None, None, None

def load_config():
    """加载 skill 根目录的 config.yml"""
    cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.yml')
    with open(cfg_path, encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def ensure_ods_index(es, host, index):
    """确保 ODS 索引存在，套用 mapping（如果不存在）

    v0.5 (2026-07-02) ：委托到 gov_price_etl.mappings.build_ods_mapping。
    新字段（区间价 price_min/max/range/is_range 等）自动生效。
    Args:
        es: elasticsearch SDK
        host: ES 地址（保留兼容位，实际未用）
        index: 索引名
    无特化字段（使用通用模板）
    """
    if es.indices.exists(index=index):
        return
    from gov_price_etl.mappings import build_ods_mapping
    mapping = build_ods_mapping()
    es.indices.create(index=index, body=mapping)

def ensure_progress_index(es, index):
    """确保同步进度索引存在

    v0.6 (2026-07-02) ：委托到 gov_price_etl.mappings.build_progress_mapping。
    单点维护 36 个进度字段（含 2026-07-02 chongqing v3 加的 percent 等）。

    _id 规则（v0.6 标准化建议）：
        区县进度：f"{run_id}__{source}__{county}__{period}"
        run 汇总：f"{run_id}__summary"
        spot check：f"{run_id}__spot__{county}"
    """    
    if es.indices.exists(index=index):
        return
    from gov_price_etl.mappings import build_progress_mapping
    es.indices.create(index=index, body=build_progress_mapping())

def fetch_list_page(cfg, page):
    """威海列表通过 dataproxy.jsp POST 抓取（jpage 插件）

    POST 形如：
      URL: /module/web/jpage/dataproxy.jsp?startrecord=1&endrecord=15&perpage=15
      body: col=1&appid=1&webid=93&path=/&columnid=28584&unitid=428350&webname=...&permissiontype=0
    响应：XML，<record> CDATA 包裹一个 <li> 列表项 HTML。

    实测：服务端忽略 startrecord/endrecord，按 page/perpage 翻页，
    且默认 groupSize=3，每次返回 3×perpage 条记录。
    我们的 page 是"组号"（每组 3 页×15 条=45 条），共 7 组（21 页）。
    """
    site = cfg['site']
    url = site['base_url'] + site['list_proxy']
    per_page = site['list_per_page']
    group_size = 3  # jpage 默认 groupSize
    startrecord = (page - 1) * per_page * group_size + 1
    endrecord = page * per_page * group_size
    full_url = f'{url}?startrecord={startrecord}&endrecord={endrecord}&perpage={per_page}'
    data = {
        'col': 1,
        'appid': 1,
        'webid': site['list_webid'],
        'path': '/',
        'columnid': site['list_columnid'],
        'sourceContentType': 1,
        'unitid': site['list_unitid'],
        'webname': site['list_webname'],
        'permissiontype': 0,
    }
    headers = {
        'User-Agent': site['user_agent'],
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': site['base_url'] + site['list_path'],
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    }
    resp = requests.post(full_url, headers=headers, data=data, timeout=site['timeout_sec'])
    resp.raise_for_status()
    return resp.content.decode('utf-8', errors='replace')

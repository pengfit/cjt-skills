"""威海工程造价信息采集 - 工具函数"""
import os
import sys

import yaml

# v0.7 (2026-07-02) P1 抽取：工具函数委托到 gov_price_etl.collectors
sys.path.insert(0, '/Users/pengfit/.openclaw/workspace/skills/gov-price-etl')
from gov_price_etl.collectors import ( get_es_client, get_s3_client, ensure_bucket,
    upload_to_minio, minio_object_url, fetch_html, download_file,
)

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
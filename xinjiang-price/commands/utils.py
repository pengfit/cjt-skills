"""新疆工程造价信息采集 - 工具函数"""
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


def ensure_ods_index(es, index):
    """确保 ODS 索引存在。

    v0.5 (2026-07-02) ：委托到 gov_price_etl.mappings.build_ods_mapping。
    新疆特化字段（sheet_name / area_name 等）传 city_extension。
    """
    if es.indices.exists(index=index):
        return
    from gov_price_etl.mappings import build_ods_mapping
    # 新疆特化：sheet_name (xlsx 多 sheet) / areaid / area_name
    mapping = build_ods_mapping(city_extension={
        'sheet_name':  {'type': 'keyword'},
        'areaid':      {'type': 'integer'},
        'area_name':   {'type': 'keyword'},
    })
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

def http_post(url, data, headers=None, timeout=30):
    """新疆列表接口用 application/x-www-form-urlencoded POST"""
    h = {'User-Agent': 'Mozilla/5.0', 'X-Requested-With': 'XMLHttpRequest'}
    if headers:
        h.update(headers)
    resp = requests.post(url, data=data, headers=h, timeout=timeout)
    resp.raise_for_status()
    return resp.json()

def http_get(url, headers=None, timeout=30):
    h = {'User-Agent': 'Mozilla/5.0'}
    if headers:
        h.update(headers)
    resp = requests.get(url, headers=h, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    return resp.text

def extract_period(title, target_year):
    """从政策标题解析 period 与 year，例如 '伊犁州2026年4月份建设工程综合价格信息' → ('2026-04-01', 2026)"""
    m = YEAR_RE.search(title or '')
    if not m:
        return '', 0
    y, mo = int(m.group(1)), int(m.group(2))
    if y != target_year:
        return '', y
    return f'{y:04d}-{mo:02d}-01', y

def area_label(area):
    """area = {areaid, name, city} → '伊犁 (伊犁哈萨克自治州)'"""
    if area.get('city') and area['city'] != area['name']:
        return f"{area['name']} ({area['city']})"
    return area.get('name', '')

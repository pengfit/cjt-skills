"""新疆工程造价信息采集 - 工具函数"""
import os
import re
import sys

import boto3
import requests
import yaml
from botocore.client import Config
from elasticsearch import Elasticsearch

# 复用 gov_price_etl 通用层（ODS mapping 标准化）
_ETL_PROJECT_ROOT = os.path.expanduser("~/.openclaw/workspace/skills/gov-price-etl")
if os.path.isdir(_ETL_PROJECT_ROOT) and _ETL_PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _ETL_PROJECT_ROOT)


def load_config():
    cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.yml')
    with open(cfg_path) as f:
        return yaml.safe_load(f)


def get_es_client(host):
    return Elasticsearch([host], request_timeout=30)


def get_s3_client(cfg):
    m = cfg['minio']
    return boto3.client(
        's3',
        endpoint_url=m['endpoint'],
        aws_access_key_id=m['access_key'],
        aws_secret_access_key=m['secret_key'],
        config=Config(signature_version='s3v4'),
        region_name='us-east-1',
    )


def ensure_bucket(s3, bucket):
    try:
        s3.head_bucket(Bucket=bucket)
    except Exception:
        s3.create_bucket(Bucket=bucket)


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


def download_file(url, dest, headers=None, timeout=120):
    h = {'User-Agent': 'Mozilla/5.0'}
    if headers:
        h.update(headers)
    with requests.get(url, headers=h, timeout=timeout, stream=True) as r:
        r.raise_for_status()
        with open(dest, 'wb') as f:
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if chunk:
                    f.write(chunk)
    return dest


def upload_to_minio(s3, bucket, key, file_path, content_type='application/octet-stream'):
    s3.upload_file(file_path, bucket, key, ExtraArgs={'ContentType': content_type})


# ─── 业务工具 ────────────────────────────────────────────────────────────────
YEAR_RE = re.compile(r'(\d{4})\s*年\s*(\d{1,2})\s*月')


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

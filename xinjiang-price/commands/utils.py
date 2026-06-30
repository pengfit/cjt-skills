"""新疆工程造价信息采集 - 工具函数"""
import os
import re
import sys

import boto3
import requests
import yaml
from botocore.client import Config
from elasticsearch import Elasticsearch


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
    """确保 ODS 索引存在（新疆字段对齐 chongqing/jiangsu 等 SKU 城市格式）"""
    if es.indices.exists(index=index):
        return
    mapping = {
        'settings': {'number_of_shards': 1, 'number_of_replicas': 0},
        'mappings': {
            'properties': {
                'breed':         {'type': 'text', 'fields': {'keyword': {'type': 'keyword', 'ignore_above': 512}}},
                'breed_clean':   {'type': 'keyword'},
                'spec':          {'type': 'text', 'fields': {'keyword': {'type': 'keyword', 'ignore_above': 512}}},
                'unit':          {'type': 'keyword'},
                'price':         {'type': 'float'},
                'tax_price':     {'type': 'float'},
                'category':      {'type': 'keyword'},
                'period':        {'type': 'keyword'},
                'province':      {'type': 'keyword'},
                'city':          {'type': 'keyword'},
                'county':        {'type': 'keyword'},
                'update_date':   {'type': 'date', 'format': 'yyyy-MM-dd'},
                'create_time':   {'type': 'date', 'format': 'yyyy-MM-dd HH:mm:ss'},
                'source_file':   {'type': 'keyword'},
                'source_url':    {'type': 'keyword'},
                'source_id':     {'type': 'keyword'},
                'sheet_name':    {'type': 'keyword'},
            },
        },
    }
    es.indices.create(index=index, body=mapping)


def ensure_progress_index(es, index):
    if es.indices.exists(index=index):
        return
    es.indices.create(index=index, body={
        'settings': {'number_of_shards': 1, 'number_of_replicas': 0},
        'mappings': {
            'properties': {
                'areaid':        {'type': 'keyword'},
                'area_name':     {'type': 'keyword'},
                'period':        {'type': 'keyword'},
                'policy_id':     {'type': 'keyword'},
                'policy_title':  {'type': 'text'},
                'release_date':  {'type': 'keyword'},
                'file_url':      {'type': 'keyword'},
                'minio_key':     {'type': 'keyword'},
                'docs_written':  {'type': 'integer'},
                'status':        {'type': 'keyword'},
                'error':         {'type': 'text'},
                'duration_sec':  {'type': 'float'},
                'created_at':    {'type': 'keyword'},
            },
        },
    })


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

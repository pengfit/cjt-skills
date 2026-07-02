"""海南工程造价信息采集 - 工具函数"""
import os
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
    """加载 skill 根目录的 config.yml"""
    cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.yml')
    with open(cfg_path) as f:
        return yaml.safe_load(f)


def get_es_client(host):
    return Elasticsearch([host], request_timeout=30)


def get_s3_client(cfg):
    """获取 MinIO S3 客户端"""
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
    """确保 bucket 存在（不存在则创建）"""
    try:
        s3.head_bucket(Bucket=bucket)
    except Exception:
        s3.create_bucket(Bucket=bucket)


def ensure_ods_index(es, host, index):
    """确保 ODS 索引存在，套用 mapping（如果不存在）

    v0.5 (2026-07-02) ：委托到 gov_price_etl.mappings.build_ods_mapping。
    新字段（区间价 price_min/max/range/is_range 等）自动生效。
    """
    if es.indices.exists(index=index):
        return
    from gov_price_etl.mappings import build_ods_mapping
    mapping = build_ods_mapping()
    es.indices.create(index=index, body=mapping)


def ensure_progress_index(es, index):
    """确保同步进度索引存在"""
    if es.indices.exists(index=index):
        return
    es.indices.create(index=index, body={
        'settings': {'number_of_shards': 1, 'number_of_replicas': 0},
        'mappings': {
            'properties': {
                'period':         {'type': 'keyword'},
                'publish_date':   {'type': 'keyword'},
                'detail_url':     {'type': 'keyword'},
                'pdf_url':        {'type': 'keyword'},
                'minio_key':      {'type': 'keyword'},
                'docs_written':   {'type': 'integer'},
                'status':         {'type': 'keyword'},
                'error':          {'type': 'text'},
                'duration_sec':   {'type': 'float'},
                'created_at':     {'type': 'keyword'},
            },
        },
    })


def fetch_html(url, headers=None, timeout=30):
    """HTTP GET 拿 HTML 文本"""
    h = headers or {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
    resp = requests.get(url, headers=h, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    return resp.text


def download_file(url, dest, headers=None, timeout=600):
    """HTTP GET 下载到本地路径（海南站点较慢，默认 600s timeout）"""
    h = headers or {'User-Agent': 'Mozilla/5.0'}
    with requests.get(url, headers=h, timeout=timeout, stream=True) as r:
        r.raise_for_status()
        with open(dest, 'wb') as f:
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if chunk:
                    f.write(chunk)
    return dest


def upload_to_minio(s3, bucket, key, file_path, content_type='application/pdf'):
    """上传本地文件到 MinIO"""
    s3.upload_file(file_path, bucket, key, ExtraArgs={'ContentType': content_type})


def minio_object_url(s3, bucket, key, expires=3600):
    """生成 MinIO 对象的预签名 URL（短时访问用）"""
    return s3.generate_presigned_url(
        'get_object', Params={'Bucket': bucket, 'Key': key}, ExpiresIn=expires
    )

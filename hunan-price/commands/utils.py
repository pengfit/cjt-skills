"""湖南建设工程材料价格行情 - 工具函数"""
import os
import sys

import boto3
import requests
import yaml
from botocore.client import Config
from elasticsearch import Elasticsearch


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
    """确保 ODS 索引存在，套用标准 mapping（v0.8, 2026-07-03）

    v0.5 起使用 gov_price_etl.mappings.build_ods_mapping(city_extension=...)
    统一标准字段 + 城市特化字段，含 period_start/end/days（v0.5 新增）
    """
    if es.indices.exists(index=index):
        return
    # 委托到 ETL 的标准 mapping（v0.5 起）
    _etl_path = '/Users/pengfit/.openclaw/workspace/skills/gov-price-etl'
    if _etl_path not in sys.path:
        sys.path.insert(0, _etl_path)
    from gov_price_etl.mappings import build_ods_mapping

    # hunan 特化字段：no, code, change_rate, index_value, period_sub, price_kind, minio_key, source_pdf, section
    city_extension = {
        'no':            {'type': 'keyword'},
        'code':          {'type': 'keyword'},
        'change_rate':   {'type': 'float'},
        'index_value':   {'type': 'float'},
        'period_sub':    {'type': 'keyword'},
        'price_kind':    {'type': 'keyword'},
        'minio_key':     {'type': 'keyword'},
        'source_pdf':    {'type': 'keyword'},
        'section':       {'type': 'text', 'fields': {'keyword': {'type': 'keyword', 'ignore_above': 256}}},
        'update_date':   {'type': 'keyword'},
        'create_time':   {'type': 'keyword'},
    }
    mapping = build_ods_mapping(city_extension=city_extension)
    es.indices.create(index=index, body=mapping)


def ensure_progress_index(es, index):
    """确保同步进度索引存在（v0.8 委托到 ETL 标准 mapping）"""
    if es.indices.exists(index=index):
        return
    _etl_path = '/Users/pengfit/.openclaw/workspace/skills/gov-price-etl'
    if _etl_path not in sys.path:
        sys.path.insert(0, _etl_path)
    from gov_price_etl.mappings import build_progress_mapping

    # hunan 特化进度字段
    city_extension = {
        'publish_date':   {'type': 'keyword'},
        'duration_sec':   {'type': 'float'},
        'created_at':     {'type': 'keyword'},
    }
    mapping = build_progress_mapping(city_extension=city_extension)
    es.indices.create(index=index, body=mapping)


def fetch_html(url, headers=None, timeout=30):
    """HTTP GET 拿 HTML 文本"""
    h = headers or {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
    try:
        resp = requests.get(url, headers=h, timeout=timeout)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        return resp.text
    except (requests.exceptions.SSLError, requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        # 回退：使用 curl 接受不安全 renegotiation（老旧政府网站常见）
        import subprocess
        ua = h.get('User-Agent', 'Mozilla/5.0')
        r = subprocess.run(
            ['curl', '-k', '-L', '-A', ua, '-s', '--max-time', str(timeout), url],
            capture_output=True, text=True, timeout=timeout + 10
        )
        if r.returncode != 0:
            raise RuntimeError(f'curl fallback failed: rc={r.returncode} stderr={r.stderr[:200]}')
        return r.stdout


def download_file(url, dest, headers=None, timeout=60):
    """HTTP GET 下载到本地路径"""
    h = headers or {'User-Agent': 'Mozilla/5.0'}
    try:
        with requests.get(url, headers=h, timeout=timeout, stream=True) as r:
            r.raise_for_status()
            with open(dest, 'wb') as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
        return dest
    except (requests.exceptions.SSLError, requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        # 回退：使用 curl -k
        import subprocess
        ua = h.get('User-Agent', 'Mozilla/5.0')
        r = subprocess.run(
            ['curl', '-k', '-L', '-A', ua, '-s', '--max-time', str(timeout), url, '-o', dest],
            capture_output=True, text=True, timeout=timeout + 10
        )
        if r.returncode != 0:
            raise RuntimeError(f'curl fallback failed: rc={r.returncode} stderr={r.stderr[:200]}')
        return dest


def upload_to_minio(s3, bucket, key, file_path, content_type='application/pdf'):
    """上传本地文件到 MinIO"""
    s3.upload_file(file_path, bucket, key, ExtraArgs={'ContentType': content_type})


def minio_object_url(s3, bucket, key, expires=3600):
    """生成 MinIO 对象的预签名 URL（短时访问用）"""
    return s3.generate_presigned_url(
        'get_object', Params={'Bucket': bucket, 'Key': key}, ExpiresIn=expires
    )
"""威海工程造价信息采集 - 工具函数"""
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



def fetch_html(url, headers=None, timeout=30):
    """HTTP GET 拿 HTML 文本"""
    h = headers or {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
    resp = requests.get(url, headers=h, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    return resp.text


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


def download_file(url, dest, referer=None, headers=None, timeout=60):
    """HTTP GET 下载到本地路径（自动跟随 302 重定向）

    威海 PDF 通过 downfile.jsp 302 重定向到 /attach/0/xxx.pdf，requests 默认跟随。
    """
    h = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
    if headers:
        h.update(headers)
    if referer:
        h['Referer'] = referer
    with requests.get(url, headers=h, timeout=timeout, stream=True, allow_redirects=True) as r:
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

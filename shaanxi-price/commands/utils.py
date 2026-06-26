"""陕西省工程造价材料信息采集 - 工具函数"""
import os
import re

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


def ensure_ods_index(es, index):
    """确保 ODS 索引存在，套用 mapping"""
    if es.indices.exists(index=index):
        return
    mapping = {
        'settings': {'number_of_shards': 1, 'number_of_replicas': 0},
        'mappings': {
            'properties': {
                'code':          {'type': 'keyword'},
                'breed':         {'type': 'text', 'fields': {'keyword': {'type': 'keyword', 'ignore_above': 512}}},
                'breed_clean':   {'type': 'keyword'},
                'spec':          {'type': 'text', 'fields': {'keyword': {'type': 'keyword', 'ignore_above': 512}}},
                'unit':          {'type': 'keyword'},
                'price':         {'type': 'float'},
                'tax_price':     {'type': 'float'},
                'period':        {'type': 'keyword'},
                'province':      {'type': 'keyword'},
                'city':          {'type': 'keyword'},
                'county':        {'type': 'keyword'},
                'category':      {'type': 'keyword'},
                'update_date':   {'type': 'keyword'},
                'create_time':   {'type': 'keyword'},
                'source_pdf':    {'type': 'keyword'},
                'source_url':    {'type': 'keyword'},
            },
        },
    }
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
                'title':          {'type': 'text'},
                'city':           {'type': 'keyword'},
                'publish_date':   {'type': 'keyword'},
                'detail_url':     {'type': 'keyword'},
                'pdf_url':        {'type': 'keyword'},
                'minio_key':      {'type': 'keyword'},
                'docs_written':   {'type': 'integer'},
                'pages_parsed':   {'type': 'integer'},
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


def download_file(url, dest, headers=None, timeout=120):
    """HTTP GET 下载到本地路径"""
    h = headers or {'User-Agent': 'Mozilla/5.0'}
    with requests.get(url, headers=h, timeout=timeout, stream=True) as r:
        r.raise_for_status()
        with open(dest, 'wb') as f:
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if chunk:
                    f.write(chunk)
    return dest


def upload_to_minio(s3, bucket, key, file_path, content_type='application/pdf'):
    s3.upload_file(file_path, bucket, key, ExtraArgs={'ContentType': content_type})


def minio_object_url(s3, bucket, key, expires=3600):
    return s3.generate_presigned_url(
        'get_object', Params={'Bucket': bucket, 'Key': key}, ExpiresIn=expires
    )


# ─── 列表/详情/标题 解析辅助 ───────────────────────────────────────────────

def parse_list_page(html, base_url):
    """从列表页 HTML 提取每期信息。
    
    列表结构：
      <li class="clearfix">
        <a href="./202606/t20260612_3646847.html" title="设区市造价信息---...">设区市造价信息---...</a>
        <span>2026-06-12</span>
      </li>
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    items = []
    for li in soup.select('li.clearfix'):
        a = li.select_one('a')
        if not a:
            continue
        href = a.get('href', '')
        # 必须是详情页 URL（相对路径 ./YYYYMM/tYYYYMMDD_NNN.html）
        if not re.search(r'/t\d{8}_\d+\.html$', href):
            continue
        title = a.get('title', '') or a.get_text(strip=True)
        # 日期可能在 <span> 或 <em> 或直接文本
        date_el = li.select_one('span')
        publish_date = date_el.get_text(strip=True) if date_el else ''
        # 兜底：从 URL 中提取
        if not publish_date:
            m = re.search(r'/t(\d{8})_', href)
            if m:
                d = m.group(1)
                publish_date = f'{d[:4]}-{d[4:6]}-{d[6:8]}'
        from urllib.parse import urljoin
        items.append({
            'title': title,
            'publish_date': publish_date,
            'detail_url': urljoin(base_url, href),
        })
    return items


def parse_detail_page(html, base_url):
    """从详情页提取 PDF 链接 + 标题。
    
    结构：
      <p class="insertfileTag">
        <a appendix="true" href="./P020260612342787864103.pdf" 
           title="《安康建设工程造价信息》2026年第5期.pdf"
           download="《安康建设工程造价信息》2026年第5期.pdf"
           OLDSRC="/protect/P0202606/P020260612/P020260612342787864103.pdf">
           《安康建设工程造价信息》2026年第5期.pdf</a>
      </p>
    """
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    soup = BeautifulSoup(html, 'html.parser')
    # 优先取第一个带 appendix="true" 的 PDF 链接
    pdf_a = None
    for a in soup.select('a[href*=".pdf"]'):
        appendix = a.get('appendix', '')
        if appendix.lower() == 'true' or 'needdownload' in a.attrs:
            pdf_a = a
            break
    if pdf_a is None:
        # 兜底：取第一个 .pdf 链接
        pdf_a = soup.select_one('a[href*=".pdf"]')

    if pdf_a is None:
        return {'title': '', 'pdf_url': '', 'pdf_name': ''}

    href = pdf_a.get('href', '')
    # 优先使用 download 属性作为文件名（更可靠）
    pdf_name = pdf_a.get('download', '') or pdf_a.get('title', '') or pdf_a.get_text(strip=True)
    # 去除外层《》
    pdf_name = pdf_name.strip().strip('《》')

    # 解析真实 PDF URL：href 是相对路径（./P020...），加上 detail 路径前缀
    if href.startswith('./'):
        # 详情页 URL 是 .../{YYYYMM}/tYYYYMMDD_NNN.html
        # PDF URL 是 .../{YYYYMM}/P020YYMMDDNNNN.pdf
        detail_dir = base_url.rsplit('/', 1)[0]  # 取详情页所在目录
        pdf_url = detail_dir + '/' + href[2:]
    else:
        pdf_url = urljoin(base_url, href)

    # title 取自页面 h1 / title-tag
    title_el = soup.select_one('h1, div.article-title, div.ewb-info-tt, .title')
    title = title_el.get_text(strip=True) if title_el else pdf_name

    return {'title': title, 'pdf_url': pdf_url, 'pdf_name': pdf_name}


def extract_period_from_title(title):
    """从标题提取 period。
    
    模式：
      《安康建设工程造价信息》2026年第5期       → 2026.5期
      《商洛工程造价管理信息》2026年第1期（季刊） → 2026.1期(季刊)
      《渭南工程造价信息》2026年2期（双月刊）    → 2026.2期
      2026年5月材料信息价                       → 2026.5月
    """
    title = title or ''
    # 第 X 期（季刊/双月刊/月刊）
    m = re.search(r'(\d{4})年第(\d{1,2})期', title)
    if m:
        year, issue = int(m.group(1)), int(m.group(2))
        suffix = ''
        if '季刊' in title:
            suffix = '(季刊)'
        elif '双月刊' in title:
            suffix = '(双月刊)'
        elif '月刊' in title:
            suffix = '(月刊)'
        return f'{year}.{issue}期{suffix}'

    # 年 X 期（不带"第"字）
    m = re.search(r'(\d{4})年(\d{1,2})期', title)
    if m:
        year, issue = int(m.group(1)), int(m.group(2))
        suffix = ''
        if '季刊' in title:
            suffix = '(季刊)'
        elif '双月刊' in title:
            suffix = '(双月刊)'
        elif '月刊' in title:
            suffix = '(月刊)'
        return f'{year}.{issue}期{suffix}'

    # 年 X 月材料信息价
    m = re.search(r'(\d{4})年(\d{1,2})月', title)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        return f'{year}.{month}月'

    return ''


def extract_city_from_title(title, city_patterns, province_label):
    """从标题提取 city。
    
    模式：
      设区市造价信息---《安康建设工程造价信息》2026年第5期  → 安康
      设区市造价信息---《汉中建设工程造价信息》...        → 汉中
      2026年5月材料信息价                                  → 陕西 (省本级)
    """
    title = title or ''
    for city in city_patterns:
        if city in title:
            return city
    # 兜底：标题里有"造价信息"但不是设区市 → 省本级
    if '造价信息' in title or '材料信息价' in title:
        return province_label
    return province_label  # 默认省本级

"""collectors/client.py - 采集器通用工具（v0.7, 2026-07-02）

17 个 city skill 的 utils.py 之前各自实现 get_es_client / MinIO / HTTP 工具函数，
约 200 行重复代码。P1 阶段抽到这一份集中维护。

load_config **不抽**（v0.7 决策记录）：
- 各城市 utils.py 用 `os.path.dirname(__file__)` 反推 config.yml 路径
- 想用 inspect.stack() / sys._getframe() 自动推断 caller 路径不可靠——Python
  `from module import func` 语义下 func() 调用栈里没有原 module 帧
- 改为各城市保留自己的 load_config()，但 yaml 读取 3 行（safe_load + 文件存在 +
  空 fallback）抽到这里供 sync.py 复用

设计原则：
- 函数签名兼容老调用（默认参数吸收小差异）
- requests 风格和 SDK 风格都兼容（参见 get_es_client / get_requests_session）
- content_type 等默认参数按主流场景设（PDF），少数 xlsx 场景调用时显式传
"""
from __future__ import annotations

import os
from typing import Optional

import boto3
import requests
import yaml
from botocore.client import Config
from elasticsearch import Elasticsearch


# ─────────────────────────────────────────────────────────────
# ES 客户端
# ─────────────────────────────────────────────────────────────

def get_es_client(host: str) -> Elasticsearch:
    """返回 Elasticsearch SDK 实例（统一 request_timeout=30）。

    v0.7 抽取：11 个 es SDK 城市之前各自定义 `Elasticsearch([host], request_timeout=30)`。
    现统一委托到此函数。

    Args:
        host: ES 地址，如 'http://localhost:59200'

    Returns:
        elasticsearch.Elasticsearch 实例。
    """
    return Elasticsearch([host], request_timeout=30)


def get_requests_session() -> requests.Session:
    """返回不带代理配置的 requests.Session。

    适用 4 个 requests 城市（xian/sichuan/jinan/rizhao），trust_env=False
    避免 macOS 系统代理自动注入。
    """
    s = requests.Session()
    s.trust_env = False
    return s


# ─────────────────────────────────────────────────────────────
# MinIO / S3 客户端
# ─────────────────────────────────────────────────────────────

def get_s3_client(cfg: dict):
    """从 config['minio'] 构造 boto3 S3 client。

    v0.7 抽取：10 个 PDF 类城市（qingdao/weihai/.../shaanxi/hainan/henan）+ xinjiang
    之前各自定义 boto3.client('s3', ...)。

    Args:
        cfg: config['minio'] 段，含 endpoint/access_key/secret_key 字段。
    """
    m = cfg['minio']
    return boto3.client(
        's3',
        endpoint_url=m['endpoint'],
        aws_access_key_id=m['access_key'],
        aws_secret_access_key=m['secret_key'],
        config=Config(signature_version='s3v4'),
        region_name='us-east-1',
    )


def ensure_bucket(s3, bucket: str) -> None:
    """确保 bucket 存在（不存在则创建）。

    v0.7 抽取：11 个城市之前各自实现 try head_bucket except create_bucket。
    """
    try:
        s3.head_bucket(Bucket=bucket)
    except Exception:
        s3.create_bucket(Bucket=bucket)


def upload_to_minio(
    s3, bucket: str, key: str, file_path: str,
    content_type: str = 'application/pdf',
) -> str:
    """上传文件到 MinIO，返回 s3:// URI。

    v0.7 抽取：content_type 默认 'application/pdf'（10 个 PDF 城市默认），
    xinjiang 等 xlsx 场景调用时显式传 'application/octet-stream'。
    """
    s3.upload_file(file_path, bucket, key, ExtraArgs={'ContentType': content_type})
    return f"s3://{bucket}/{key}"


def minio_object_url(s3, bucket: str, key: str, expires: int = 3600) -> str:
    """生成 MinIO 临时访问 URL（presigned）。

    v0.7 抽取：默认 expires=3600 秒（10 个城市默认值）。
    """
    return s3.generate_presigned_url(
        'get_object',
        Params={'Bucket': bucket, 'Key': key},
        ExpiresIn=expires,
    )


# ─────────────────────────────────────────────────────────────
# HTTP 工具
# ─────────────────────────────────────────────────────────────

_DEFAULT_USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'


def _curl_fallback_get(url: str, dest: str | None, headers: dict, timeout: int):
    """SSL renegotiation 失败时回退到 curl -k（适用于老旧政府网站 zjt.jiangxi 等）

    v0.7.1 (2026-07-03) P1 加：17 个 city skill 抽出 utils 时丢了 jiangxi-price 的
    curl -k 兜底逻辑（SSL: UNSAFE_LEGACY_RENEGOTIATION_DISABLED）。本兜底对其他城市
    无副作用（其他城市 SSL 正常，requests 直接成功，根本不会走到 except 分支）。

    Args:
        dest: 文件路径，None 时输出到 stdout（HTML）；非 None 时 -o $dest
    """
    import subprocess
    ua = headers.get('User-Agent', _DEFAULT_USER_AGENT)
    cmd = ['curl', '-k', '-L', '-A', ua, '-s', '--max-time', str(timeout), url]
    if dest is not None:
        cmd += ['-o', dest]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
    if r.returncode != 0:
        raise RuntimeError(f'curl fallback failed: rc={r.returncode} stderr={r.stderr[:200]}')
    return r.stdout


def fetch_html(url: str, headers: Optional[dict] = None, timeout: int = 30) -> str:
    """GET 页面 HTML，返回 text（raise_for_status）。

    v0.7 抽取：10 个城市（qingdao/weihai/.../shaanxi/hainan/henan）之前各自定义。
    中文站自动用 apparent_encoding 检测 GBK/GB2312。

    v0.7.1 (2026-07-03) P1 加：SSL renegotiation 失败回退到 curl -k（jiangxi 等老旧站）。
    """
    h = {'User-Agent': _DEFAULT_USER_AGENT}
    if headers:
        h.update(headers)
    try:
        r = requests.get(url, headers=h, timeout=timeout, verify=False)
        r.raise_for_status()
        r.encoding = r.apparent_encoding  # 中文站编码自动检测
        return r.text
    except (requests.exceptions.SSLError, requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        return _curl_fallback_get(url, None, h, timeout)


def http_get(url: str, headers: Optional[dict] = None, timeout: int = 30) -> requests.Response:
    """GET 请求，返回 Response 对象（不 raise）。

    v0.7 抽取：xinjiang 等少数城市使用。
    """
    return requests.get(url, headers=headers, timeout=timeout, verify=False)


def http_post(
    url: str,
    data: dict,
    headers: Optional[dict] = None,
    timeout: int = 30,
) -> requests.Response:
    """POST 请求（json body），返回 Response 对象（不 raise）。

    v0.7 抽取：xinjiang 使用。
    """
    return requests.post(url, json=data, headers=headers, timeout=timeout, verify=False)


def download_file(
    url: str,
    dest: str,
    referer: Optional[str] = None,
    headers: Optional[dict] = None,
    timeout: int = 60,
) -> str:
    """下载文件到本地路径，返回 dest。

    v0.7 抽取：11 个城市之前各自定义，timeout 默认 60 秒（绝大多数），
    henan/hainan 调用时显式传 600/600（大文件）。User-Agent 默认注入。

    v0.7.1 (2026-07-03) P1 加：SSL renegotiation 失败回退到 curl -k（jiangxi 等老旧站）。

    Args:
        referer: 可选，自动加到 headers
    """
    hdrs = {'User-Agent': _DEFAULT_USER_AGENT}
    if headers:
        hdrs.update(headers)
    if referer:
        hdrs.setdefault('Referer', referer)
    try:
        with requests.get(url, headers=hdrs, timeout=timeout, stream=True, verify=False) as r:
            r.raise_for_status()
            with open(dest, 'wb') as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
        return dest
    except (requests.exceptions.SSLError, requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        _curl_fallback_get(url, dest, hdrs, timeout)
        return dest
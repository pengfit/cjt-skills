"""collectors - 采集器通用工具（v0.7, 2026-07-02）

P1 阶段抽取：17 个 city skill 的 utils.py 工具函数（约 200 行重复代码）
集中维护到 collectors 子包。

子模块：
- client: get_es_client / MinIO / HTTP 通用工具
- load_config 不抽（v0.7 决策），各城市保留自己的路径反推逻辑
"""
from .client import (
    get_es_client,
    get_requests_session,
    get_s3_client,
    ensure_bucket,
    upload_to_minio,
    minio_object_url,
    fetch_html,
    http_get,
    http_post,
    download_file,
)

__all__ = [
    "get_es_client",
    "get_requests_session",
    "get_s3_client",
    "ensure_bucket",
    "upload_to_minio",
    "minio_object_url",
    "fetch_html",
    "http_get",
    "http_post",
    "download_file",
]
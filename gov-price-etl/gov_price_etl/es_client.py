"""es_client.py - ES HTTP 客户端 + 批量写入

不引入 elasticsearch 官方 SDK，直接用 requests（更轻、依赖更少）。
所有 session 都关掉 trust_env（避免 macOS 系统代理自动注入）。
"""
import json
import time
from typing import List, Optional, Tuple

import requests


def get_es_client(host: str) -> requests.Session:
    """返回不带代理配置的 requests Session。"""
    s = requests.Session()
    s.trust_env = False  # 禁用系统代理
    return s


def bulk_index(
    es_host: str,
    index: str,
    docs: list,
    ids: Optional[list] = None,
    timeout: int = 60,
) -> Tuple[int, int]:
    """Bulk 写入 docs 到 index。返回 (成功数, 错误数)。"""
    if not docs:
        return 0, 0
    body = ""
    for i, doc in enumerate(docs):
        doc_id = ids[i] if ids and i < len(ids) else None
        action = {"index": {"_index": index}}
        if doc_id:
            action["index"]["_id"] = doc_id
        body += json.dumps(action, ensure_ascii=False) + "\n"
        body += json.dumps(doc, ensure_ascii=False) + "\n"
    try:
        resp = requests.post(
            f"{es_host}/_bulk",
            data=body.encode("utf-8"),
            headers={"Content-Type": "application/x-ndjson"},
            timeout=timeout,
        )
        if resp.status_code in (200, 201):
            items = resp.json().get("items", [])
            written = sum(1 for it in items if it.get("index", {}).get("result") in ("created", "updated"))
            errors = sum(1 for it in items if it.get("index", {}).get("error"))
            return written, errors
    except Exception as e:
        print(f"  [ERROR] bulk_index: {e}")
    return 0, len(docs)

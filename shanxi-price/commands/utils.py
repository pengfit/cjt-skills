"""山西工程造价信息采集 - 工具函数"""
def _resolve_etl_root():
    """解析 gov-price-etl 项目根路径（同 guizhou/utils.py 模式）。"""
    import os
    from pathlib import Path
    env = os.environ.get("GOV_PRICE_ETL_ROOT")
    if env and os.path.isdir(env):
        return env
    p = Path(__file__).resolve().parent
    for _ in range(6):
        candidate = p / "gov-price-etl"
        if candidate.is_dir():
            return str(candidate)
        p = p.parent
    workspace_root = Path.home() / ".openclaw" / "workspace"
    if workspace_root.is_dir():
        for ws in workspace_root.iterdir():
            candidate = ws / "skills" / "gov-price-etl"
            if candidate.is_dir():
                return str(candidate)
    raise FileNotFoundError(
        "找不到 gov-price-etl 项目根。"
        "请设置环境变量 GOV_PRICE_ETL_ROOT 指向项目根，"
        "或确认 ETL 已部署在 <workspace>/skills/gov-price-etl。"
    )


import os
import sys

import requests
import yaml

_etl_root = _resolve_etl_root()
if os.path.isdir(_etl_root) and _etl_root not in sys.path:
    sys.path.insert(0, _etl_root)
from gov_price_etl.collectors import (
    get_es_client, get_s3_client, ensure_bucket,
    upload_to_minio, fetch_html, download_file,
)


def load_config():
    """加载 skill 根目录的 config.yml。"""
    cfg_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'config.yml',
    )
    with open(cfg_path, encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def ensure_ods_index(es, host, index):
    """确保 ODS 索引存在，套用 ETL 共享 mapping。"""
    if es.indices.exists(index=index):
        return
    from gov_price_etl.mappings import build_ods_mapping
    es.indices.create(index=index, body=build_ods_mapping())


def ensure_progress_index(es, index):
    """确保同步进度索引存在。"""
    if es.indices.exists(index=index):
        return
    from gov_price_etl.mappings import build_progress_mapping
    es.indices.create(index=index, body=build_progress_mapping())


def get_headers(cfg):
    """统一请求头（山西站对 UA 较敏感，Referer 必带）。"""
    return {
        'User-Agent': cfg['site']['user_agent'],
        'Referer': cfg['site'].get('referer', cfg['site']['base_url'] + cfg['site']['list_path']),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9',
    }
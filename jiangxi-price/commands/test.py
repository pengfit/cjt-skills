#!/usr/bin/env python3
"""测试 ES / MinIO 连接"""
def _resolve_etl_root():
    """解析 gov-price-etl 项目根路径。

    优先级：
      1) 环境变量 GOV_PRICE_ETL_ROOT（部署/调试可显式覆盖）
      2) 自动反推：从本文件路径向上找 'gov-price-etl' 同级目录，
         不依赖硬编码的 workspace 名 / 目录深度。
      3) 兜底扫描：~/.openclaw/workspace/*/skills/gov-price-etl,
         不预设 workspace 名。
      4) 仍找不到：抛错提示用户设环境变量。绝不默默返回错误路径。
    """
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


import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import warnings
warnings.filterwarnings('ignore')
import requests
from commands.utils import load_config

def main():
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config = load_config()
    es_host = config.get('es', {}).get('host', 'http://localhost:59200')

    # ES 连通性
    try:
        r = requests.get(f"{es_host}/_cluster/health", timeout=10, verify=False)
        print(f"[✓] ES 连接成功: {es_host}")
        print(f"    集群状态: {r.json().get('status')}")
    except Exception as e:
        print(f"[✗] ES 连接失败: {e}")
        return

    # MinIO 连通性
    m = config.get('minio', {})
    try:
        import boto3
        from botocore.client import Config
        s3 = boto3.client(
            's3',
            endpoint_url=m.get('endpoint'),
            aws_access_key_id=m.get('access_key'),
            aws_secret_access_key=m.get('secret_key'),
            config=Config(signature_version='s3v4'),
            region_name='us-east-1',
        )
        s3.head_bucket(Bucket=m.get('bucket'))
        print(f"[✓] MinIO 连接成功: {m.get('endpoint')} / {m.get('bucket')}")
    except Exception as e:
        print(f"[✗] MinIO 连接失败: {e}")

    # 源站连通性
    site = config.get('site', {})
    list_url = site.get('base_url', '') + site.get('list_path', '')
    try:
        _etl_root = _resolve_etl_root()
        if os.path.isdir(_etl_root) and _etl_root not in sys.path:
            sys.path.insert(0, _etl_root)
        from gov_price_etl.collectors import fetch_html
        html = fetch_html(list_url, headers={'User-Agent': site.get('user_agent', 'Mozilla/5.0')}, timeout=site.get('timeout_sec', 30))
        print(f"[✓] 源站连接成功: {list_url}")
        print(f"    列表页 HTML 长度: {len(html)}")
        if 'articleList' in html:
            print(f"    ✓ 含 articleList 嵌入 JSON")
        else:
            print(f"    ✗ 不含 articleList，源站结构可能变更")
    except Exception as e:
        print(f"[✗] 源站连接失败: {e}")


if __name__ == '__main__':
    main()
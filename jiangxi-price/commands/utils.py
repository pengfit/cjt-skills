"""江西建设工程材料信息参考价 - 工具函数（v0.9, 2026-07-03）

v0.9 改动：
- ensure_ods_index 委托到 gov_price_etl.mappings.build_ods_mapping（已抽到 ETL 标准 mapping）
- 江西特化字段：no / section / vat_rate / price_kind / region / period_start/end/days
- ensure_progress_index 委托到 gov_price_etl.mappings.build_progress_mapping
- v0.9 必含字段：period_start / period_end / period_days（道友要求字段不能缺）
"""
def _resolve_etl_root():
    """解析 gov-price-etl 项目根路径。

    优先级：
      1) 环境变量 GOV_PRICE_ETL_ROOT（部署/调试可显式覆盖）
      2) 自动反推：从本文件路径向上找 'gov-price-etl' 同级目录，
         不依赖硬编码的 workspace 名 / 目录深度。
      3) 兜底 fallback（cjt 子目录布局），让上层 log warning，不抛异常。
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
    return str(Path.home() / ".openclaw" / "workspace" / "cjt" / "skills" / "gov-price-etl")


import os
import sys

import yaml

# v0.7 (2026-07-02) P1 抽取：工具函数委托到 gov_price_etl.collectors
_etl_root = _resolve_etl_root()
if os.path.isdir(_etl_root) and _etl_root not in sys.path:
    sys.path.insert(0, _etl_root)
from gov_price_etl.collectors import (
    get_es_client, get_s3_client, ensure_bucket,
    upload_to_minio, minio_object_url, fetch_html, download_file,
)


def load_config():
    """加载 skill 根目录的 config.yml"""
    cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.yml')
    with open(cfg_path, encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def ensure_ods_index(es, host, index):
    """确保 ODS 索引存在，套用 mapping（如果不存在）

    v0.9 (2026-07-03) ：委托到 gov_price_etl.mappings.build_ods_mapping。
    必含字段 period_start / period_end / period_days（道友要求字段不能缺）由
    _ODS_BASE_FIELDS 自动声明；city_extension 只声明江西特化字段（不在 base 里的）。
    """
    if es.indices.exists(index=index):
        return
    from gov_price_etl.mappings import build_ods_mapping

    # 江西特化字段（base 已经覆盖 period_start/end/days / period / no 等通用字段）
    city_extension = {
        "section": {'type': 'text', 'fields': {'keyword': {'type': 'keyword', 'ignore_above': 256}}},
        "vat_rate": {'type': 'float'},
        "price_kind": {'type': 'keyword'},
        "region": {'type': 'keyword'},   # 县名（多县表）
    }
    mapping = build_ods_mapping(city_extension=city_extension)
    es.indices.create(index=index, body=mapping)


def ensure_progress_index(es, index):
    """确保同步进度索引存在

    v0.6 (2026-07-02) ：委托到 gov_price_etl.mappings.build_progress_mapping。
    v0.9 (2026-07-03) ：加 city_extension 声明江西特化字段（period_start/end/days 由 base 自动覆盖）。

    _id 规则（v0.6 标准化建议）：
        期刊进度：f"{run_id}__{period}"
        run 汇总：f"{run_id}__summary"
    """
    if es.indices.exists(index=index):
        return
    from gov_price_etl.mappings import build_progress_mapping

    # 江西特化字段（base 已覆盖 period_start/end/days / publish_date / pdf_url / detail_url 等）
    city_extension = {
        "publish_date": {'type': 'keyword'},     # ES 索引里 ES 推 'text'，这里统一为 keyword
        "duration_sec": {'type': 'float'},
        "created_at": {'type': 'keyword'},       # ES 推 'date'，sync 写字符串，统一为 keyword 兼容旧数据
    }
    mapping = build_progress_mapping(city_extension=city_extension)
    es.indices.create(index=index, body=mapping)
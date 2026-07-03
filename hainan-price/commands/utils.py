"""海南工程造价信息采集 - 工具函数"""
import os
import sys

import yaml

# v0.7 (2026-07-02) P1 抽取：工具函数委托到 gov_price_etl.collectors
sys.path.insert(0, '/Users/pengfit/.openclaw/workspace/skills/gov-price-etl')
from gov_price_etl.collectors import ( get_es_client, get_s3_client, ensure_bucket,
    upload_to_minio, minio_object_url, fetch_html, download_file,
)

def load_config():
    """加载 skill 根目录的 config.yml"""
    cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.yml')
    with open(cfg_path, encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def ensure_ods_index(es, host, index):
    """确保 ODS 索引存在，套用 mapping（如果不存在）

    v0.5 (2026-07-02) ：委托到 gov_price_etl.mappings.build_ods_mapping。
    新字段（区间价 price_min/max/range/is_range 等）自动生效。

    v0.8 (2026-07-02) ：补 hainan 城市特化字段 region（北部/南部/西部/东部/中部）
    和 section（一级章节：钢材/水泥...）。基础 mapping 不会主动加这些。
    """
    if es.indices.exists(index=index):
        return
    from gov_price_etl.mappings import build_ods_mapping
    mapping = build_ods_mapping(city_extension={
        # 海南区域（5 个区域分组：北部/南部/西部/东部/中部/全省）
        "region":  {"type": "keyword"},
        # 一级章节（钢材/水泥、砂石、墙体材料和预制桩/...）
        "section": {"type": "keyword"},
    })
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
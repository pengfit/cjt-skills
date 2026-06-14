"""pipeline - ETL 三段式主流程（v0.3 重构）

子模块：
  - etl        ODS → DWD 三段式 ETL（DB → Jaccard → AI 串行）
  - dws_sync   DWD → DWS 三段式同步（DWD attr → 本地规则库 → AI 串行）

公开 API：
  from gov_price_etl.pipeline import (
      # ODS → DWD
      etl_city, run_etl,
      # DWD → DWS（兼容旧入口）
      sync_dws, sync_dws_with_ai, sync_dws_plain, sync_dws_quick,
      # AI 串行批次参数
      AI_CATEGORY_BATCH_SIZE, AI_PARSE_BATCH_SIZE,
  )
"""
from .etl import (
    etl_city,
    run_etl,
    AI_CATEGORY_BATCH_SIZE,
    AI_CATEGORY_BATCH_SLEEP_S,
)
from .dws_sync import (
    sync_dws,
    sync_dws_with_ai,
    sync_dws_plain,
    sync_dws_quick,
    _dwd_to_dws_three_stages,
    _parse_spec_local,
    _ai_parse_specs_serial,
    AI_PARSE_BATCH_SIZE,
    AI_PARSE_BATCH_SLEEP_S,
)

__all__ = [
    # ODS → DWD
    "etl_city",
    "run_etl",
    "AI_CATEGORY_BATCH_SIZE",
    "AI_CATEGORY_BATCH_SLEEP_S",
    # DWD → DWS
    "sync_dws",
    "sync_dws_with_ai",
    "sync_dws_plain",
    "sync_dws_quick",
    "_dwd_to_dws_three_stages",
    "_parse_spec_local",
    "_ai_parse_specs_serial",
    "AI_PARSE_BATCH_SIZE",
    "AI_PARSE_BATCH_SLEEP_S",
]
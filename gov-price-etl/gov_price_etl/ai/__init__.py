"""ai - 统一 AI 服务入口

设计目标：
  1. ETL 与 dashboard 解耦：所有 AI 调用走这里
  2. 本地规则库前置：调 AI 之前先查 v3 规则库（category_v3_rules.db），
     命中直接返回，不调 AI（核心省钱策略）
     2026-07-18：原调 v2（category_v2_rules.db），v2 db 已不存在，改 v3
  3. **只走 Dify workflow API**（2026-06-18 起：OpenClaw gateway 路径已废）
     - 分类：app-rUtcXqTyV8N8TY0s6RhSu0GB (etl-classify-category)
     - 解析：app-kgaF6jNrpd4PytjhUk3VTCQ4 (etl-parse-spec)
  4. 统一重试：失败有 fallback（Dify client 内部 5xx 重试 + 业务层 fallback dict）
  5. 计量：每次调用都计入 stats
  6. Prompt 模板从 prompts.yml 加载（path 由 paths.PROMPTS_YML 解析），
     改 yml 后下次调用自动重读（mtime 检测）

实际调用路径：
  ETL → ai.service._ai_invoke → dify_client.DifyClient → Dify /v1/workflows/run

入口变化：
  - 2026-06-16：删除 classify_breed_batch（v1），大分类全部走 v2 4 层
  - 2026-06-19：etl-classify-v2 废弃，分类走 etl-classify-category（DeepSeek 版，内置 L3 知识库）
"""
from .service import (
    parse_spec_batch,
    classify_v3_batch,
    get_stats,
    reset_stats,
)
from .prompts import (
    get_prompts,
    get_prompt,
    reload_prompts,
    format_prompt,
    BUILTIN_FALLBACK,
)

__all__ = [
    # AI 调用
    "parse_spec_batch",
    "classify_v2_batch",
    "get_stats",
    "reset_stats",
    # Prompt 模板管理
    "get_prompts",
    "get_prompt",
    "reload_prompts",
    "format_prompt",
    "BUILTIN_FALLBACK",
]

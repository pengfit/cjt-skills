"""ai - 统一 AI 服务入口

设计目标：
  1. ETL 与 dashboard 解耦：所有 AI 调用走这里
  2. 本地规则库前置：调 AI 之前先查 breed_*_rules.db（精确+模糊），
     命中直接返回，不调 AI（这是核心省钱策略）
  3. 统一鉴权：读 openclaw.json 拿 token
  4. 统一重试：失败有 fallback
  5. 计量：每次调用都计入 stats
  6. Prompt 模板从 prompts.yml 加载（path 由 paths.PROMPTS_YML 解析），
     改 yml 后下次调用自动重读（mtime 检测）

实际调用路径（不绕道 dashboard）：
  ETL → ai.service → OpenClaw gateway (localhost:18789/v1/chat/completions)
"""
from .service import (
    parse_spec_batch,
    classify_breed_batch,
    get_stats,
    reset_stats,
    GATEWAY_URL,
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
    "classify_breed_batch",
    "get_stats",
    "reset_stats",
    "GATEWAY_URL",
    # Prompt 模板管理
    "get_prompts",
    "get_prompt",
    "reload_prompts",
    "format_prompt",
    "BUILTIN_FALLBACK",
]

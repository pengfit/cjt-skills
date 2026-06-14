"""ai - 统一 AI 服务入口（带缓存）

设计目标：
  1. ETL 与 dashboard 解耦：所有 AI 调用走这里
  2. 缓存层：重复 spec 文本不再重复送 AI（ai_cache.db）
  3. 统一鉴权：读 openclaw.json 拿 token
  4. 统一重试：失败有 fallback
  5. 计量：每次调用都计入 stats

实际调用路径（不绕道 dashboard）：
  ETL → ai.service → OpenClaw gateway (localhost:18789/v1/chat/completions)

兼容旧接口：
  - 仍接受 dashboard prompts.yml 路径（如果存在）作为 prompt 模板源
  - 若无 dashboard 则用内置简化模板（fallback）
"""
from .service import (
    parse_spec_batch,
    classify_breed_batch,
    get_stats,
    reset_stats,
    GATEWAY_URL,
)
from . import cache as _cache

__all__ = [
    "parse_spec_batch",
    "classify_breed_batch",
    "get_stats",
    "reset_stats",
    "GATEWAY_URL",
    "_cache",
]

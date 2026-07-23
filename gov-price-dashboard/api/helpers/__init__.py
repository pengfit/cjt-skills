"""gov-price-dashboard API helpers

共享工具模块，按职责拆分：
- query_builder: ES bool 查询构造
- es_safe: ES 调用的安全封装（索引缺失/异常不 500）
"""

from .query_builder import _build_bool_query
from .es_safe import (
    EMPTY_SEARCH,
    safe_search,
    safe_count,
    safe_total_count,
    filter_existing_indices,
)

__all__ = [
    "_build_bool_query",
    "EMPTY_SEARCH",
    "safe_search",
    "safe_count",
    "safe_total_count",
    "filter_existing_indices",
]

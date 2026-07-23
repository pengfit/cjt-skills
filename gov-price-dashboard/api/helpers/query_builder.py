"""ES bool 查询构建器（共享）。

所有路由的 must_clauses / filter_clauses 都用本函数统一封装成 ES bool query。
"""
from typing import List, Dict, Any


def _build_bool_query(
    must_clauses: List[Dict[str, Any]],
    filter_clauses: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """构建 ES bool 查询，处理空列表情况。

    Args:
        must_clauses: 必填子句（如 keyword match）
        filter_clauses: 过滤子句（如 term / range，不过滤 _score）

    Returns:
        ES bool 查询体。空 must → match_all；空 filter → 只 must。
    """
    must_clause = must_clauses if must_clauses else [{"match_all": {}}]
    if filter_clauses:
        return {"bool": {"must": must_clause, "filter": filter_clauses}}
    return {"bool": {"must": must_clause}}

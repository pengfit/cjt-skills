"""ES 调用的安全封装（共享）。

所有路由读写 ES 都走这里：
- safe_search / safe_count / safe_total_count：捕获索引缺失/网络异常，返回空结果而非 500
- filter_existing_indices：启动时过滤 ES 中不存在的索引（dws_*/norm_* 可能未重建）

ES client 实例从调用方传入，不在模块内单例化（保持依赖显式）。
"""
from typing import Any, Dict, Optional
from elasticsearch import (
    NotFoundError,
    RequestError,
    ConnectionError as ESConnectionError,
    ConnectionTimeout,
)


EMPTY_SEARCH: Dict[str, Any] = {
    "hits": {"total": {"value": 0}, "hits": []},
    "aggregations": {},
}


def safe_search(es, index, body, default: Optional[Dict] = None) -> Dict[str, Any]:
    """安全 ES search：索引缺失/无文档时返回 default（默认 EMPTY_SEARCH）"""
    try:
        return es.search(
            index=index,
            body=body,
            ignore_unavailable=True,
            allow_no_indices=True,
        )
    except (NotFoundError, RequestError, ESConnectionError, ConnectionTimeout):
        return default if default is not None else EMPTY_SEARCH
    except Exception as e:
        # 其他错误（聚合错误、字段不存在等）也返回空
        print(f"[warn] safe_search: {type(e).__name__}: {e}")
        return default if default is not None else EMPTY_SEARCH


def safe_count(es, index, body: Optional[Dict] = None, default: int = 0) -> int:
    """安全 ES count：索引缺失时返回 default"""
    try:
        r = es.count(
            index=index,
            body=body or {},
            ignore_unavailable=True,
            allow_no_indices=True,
        )
        return r.get("count", default)
    except (NotFoundError, RequestError, ESConnectionError, ConnectionTimeout):
        return default
    except Exception as e:
        print(f"[warn] safe_count: {type(e).__name__}: {e}")
        return default


def safe_total_count(es, index, body: Optional[Dict] = None, default: int = 0) -> int:
    """安全 ES search(track_total_hits) 返回的精确总数。

    比 safe_count 性能差一点但跨分片精确，不会被 10000 上限卡。
    用于仪表盘 total_docs 等需要精确值的场景。
    """
    try:
        payload = {"size": 0, "track_total_hits": True}
        if body:
            payload.update(body)
        r = safe_search(es, index, payload, default={"hits": {"total": {"value": default}}})
        return r.get("hits", {}).get("total", {}).get("value", default)
    except Exception as e:
        print(f"[warn] safe_total_count: {type(e).__name__}: {e}")
        return default


def filter_existing_indices(es, csv: str, log_label: str = "ALL_INDICES") -> str:
    """过滤掉 ES 中不存在的索引（用于 DWS/DWD 索引可能缺失的情况）。

    Args:
        es: ES client 实例
        csv: 逗号分隔的索引名
        log_label: 日志里显示的标签，方便区分多个索引集

    Returns:
        过滤后的 csv（仅保留 ES 中实际存在的索引）
    """
    indices = [i.strip() for i in csv.split(",") if i.strip()]
    if not indices:
        return csv
    keep = []
    for idx in indices:
        try:
            if es.indices.exists(index=idx):
                keep.append(idx)
        except Exception:
            pass
    if not keep:
        return csv
    dropped = [i for i in indices if i not in keep]
    if dropped:
        print(f"[info] {log_label} 过滤掉缺失索引: {dropped}")
    return ",".join(keep)

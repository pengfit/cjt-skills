"""/distribution 页 NORM 数据路由组：/api/norm/*  全部走 NORM_INDICES。

- /api/norm/price-distribution    ← NORM 价格区间分布(供 DistributionChart)
- /api/norm/province-ranges       ← NORM 多省价格区间一次性聚合

设计初衷（2026-07-23）：
  /distribution 页数据来源用 NORM（norm_*_price），前缀 /api/norm/ 与
  /list 页 /api/list/*（DWS）形成清晰分层；与 /api/stats/*（ALL_INDICES）解耦，
  即便 DASHBOARD_DATA_LAYER 切到 dws，本页数据来源也不受影响。
"""
from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from api.helpers import _build_bool_query, safe_search
from api.dependencies import es, NORM_INDICES

router = APIRouter()


# 区间定义（与 /api/stats/price-distribution 保持一致）
_PRICE_RANGES = [
    {"key": "50-100",     "from": 50,      "to": 100},
    {"key": "100-200",    "from": 100,     "to": 200},
    {"key": "200-500",    "from": 200,     "to": 500},
    {"key": "500-700",    "from": 500,     "to": 700},
    {"key": "700-1000",   "from": 700,     "to": 1000},
    {"key": "1000-2000",  "from": 1000,    "to": 2000},
    {"key": "2000-3000",  "from": 2000,    "to": 3000},
    {"key": "3000-4000",  "from": 3000,    "to": 4000},
    {"key": "4000-5000",  "from": 4000,    "to": 5000},
    {"key": ">5000",      "from": 5000},
]


def _keyword_clause(keyword: str):
    """NORM 层 breed 短/长词分别走 fuzzy/match_phrase（与列表页一致）"""
    if len(keyword) <= 2:
        return {"bool": {"should": [
            {"match": {"breed": keyword}},
            {"match": {"breed": {"query": keyword, "fuzziness": "AUTO", "boost": 5}}},
        ]}}
    return {"bool": {"should": [
        {"match_phrase": {"breed": {"query": keyword, "boost": 20}}},
        {"match": {"breed": {"query": keyword, "boost": 10}}},
    ]}}


# ─────────────────────────────────────────────────────────────────────
# /api/norm/price-distribution
# ─────────────────────────────────────────────────────────────────────
@router.get("/api/norm/price-distribution")
def norm_price_distribution(
    province: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    unit: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
):
    """NORM 价格区间分布（按 price 分桶 + 平均价）"""
    if not NORM_INDICES:
        return {"data": [], "warning": "NORM_INDICES 为空（未扫到 norm_*_price，请确认 ETL 已跑过归一化）"}

    must_clauses = []
    filter_clauses = []
    if keyword:
        must_clauses.append(_keyword_clause(keyword))
    if category:
        filter_clauses.append({"term": {"category": category}})
    if province:
        filter_clauses.append({"term": {"province": province}})
    if city:
        filter_clauses.append({"term": {"city": city}})
    if unit:
        filter_clauses.append({"term": {"unit": unit}})

    body = {
        "query": _build_bool_query(must_clauses, filter_clauses),
        "size": 0,
        "aggs": {
            "ranges": {
                "range": {"field": "price", "ranges": _PRICE_RANGES},
                "aggs": {"avg_price": {"avg": {"field": "price"}}},
            }
        },
    }
    try:
        result = safe_search(es, NORM_INDICES, body)
        buckets = result.get("aggregations", {}).get("ranges", {}).get("buckets", [])
        return {
            "data": [
                {
                    "range": b["key"],
                    "count": b["doc_count"],
                    "avg_price": round(b["avg_price"]["value"], 2) if b.get("avg_price", {}).get("value") else 0,
                }
                for b in buckets
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"norm_price_distribution failed: {e}")


# ─────────────────────────────────────────────────────────────────────
# /api/norm/province-ranges
# ─────────────────────────────────────────────────────────────────────
@router.get("/api/norm/province-ranges")
def norm_province_ranges(
    provinces: Optional[str] = Query(None, description="comma-separated province names"),
    category: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    unit: Optional[str] = Query(None),
):
    """NORM 多省价格区间一次性聚合（按 province+range 两层桶）"""
    if not NORM_INDICES:
        return {"data": {}, "warning": "NORM_INDICES 为空"}

    must_clauses = []
    filter_clauses = []
    if keyword:
        must_clauses.append(_keyword_clause(keyword))
    if category:
        filter_clauses.append({"term": {"category": category}})
    if unit:
        filter_clauses.append({"term": {"unit": unit}})

    prov_list = [p.strip() for p in provinces.split(",")] if provinces else []

    body = {
        "query": _build_bool_query(must_clauses, filter_clauses),
        "size": 0,
        "aggs": {
            "by_province": {
                "terms": {"field": "province", "size": 30},
                "aggs": {
                    "ranges": {
                        "range": {"field": "price", "ranges": _PRICE_RANGES},
                        "aggs": {"avg_price": {"avg": {"field": "price"}}},
                    }
                },
            }
        },
    }
    try:
        result = safe_search(es, NORM_INDICES, body)
        buckets = result.get("aggregations", {}).get("by_province", {}).get("buckets", [])
        data = {}
        for b in buckets:
            prov = b["key"]
            if prov_list and prov not in prov_list:
                continue
            data[prov] = [
                {
                    "range": rb["key"],
                    "count": rb["doc_count"],
                    "avg_price": round(rb["avg_price"]["value"], 2) if rb.get("avg_price", {}).get("value") else 0,
                }
                for rb in b["ranges"]["buckets"]
            ]
        return {"data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"norm_province_ranges failed: {e}")

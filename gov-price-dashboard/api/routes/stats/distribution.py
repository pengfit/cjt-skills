"""Phase 4 抽取: /api/stats/province-ranges (原 main.py 内联实现)"""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional

from api.helpers import _build_bool_query, safe_search
from api.dependencies import es, ALL_INDICES

router = APIRouter()

@router.get("/api/stats/province-ranges")
def province_ranges(
    provinces: Optional[str] = Query(None, description="comma-separated province names"),
    category: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    unit: Optional[str] = Query(None),
):
    """返回多个省份的价格区间分布，一次调用完成"""
    must_clauses = []
    filter_clauses = []

    if category:
        filter_clauses.append({"term": {"category": category}})
    if keyword:
        kw_len = len(keyword)
        if kw_len <= 2:
            must_clauses.append({
                "bool": {
                    "should": [
                        {"match": {"breed": keyword}},
                        {"match": {"breed": {"query": keyword, "fuzziness": "AUTO", "boost": 5}}}
                    ]
                }
            })
        else:
            must_clauses.append({
                "bool": {
                    "should": [
                        {"match_phrase": {"breed": {"query": keyword, "boost": 20}}},
                        {"match": {"breed": {"query": keyword, "operator": "and", "minimum_should_match": "100%", "boost": 10}}}
                    ]
                }
            })
    if unit:
        filter_clauses.append({"term": {"unit": unit}})

    prov_list = [p.strip() for p in provinces.split(",")] if provinces else []

    query = _build_bool_query(must_clauses, filter_clauses)
    body = {
        "query": query,
        "size": 0,
        "aggs": {
            "by_province": {
                "terms": {"field": "province", "size": 30},
                "aggs": {
                    "ranges": {
                        "range": {
                            "field": "price",
                            "ranges": [
                                {"key": "50-100",    "from": 50,  "to": 100},
                                {"key": "100-200",   "from": 100, "to": 200},
                                {"key": "200-500",   "from": 200, "to": 500},
                                {"key": "500-700",   "from": 500, "to": 700},
                                {"key": "700-1000",  "from": 700, "to": 1000},
                                {"key": "1000-2000", "from": 1000, "to": 2000},
                                {"key": "2000-3000", "from": 2000, "to": 3000},
                                {"key": "3000-4000", "from": 3000, "to": 4000},
                                {"key": "4000-5000", "from": 4000, "to": 5000},
                                {"key": ">5000",      "from": 5000},
                            ]
                        },
                        "aggs": {
                            "avg_price": {"avg": {"field": "price"}}
                        }
                    }
                }
            }
        }
    }
    try:
        result = safe_search(es, ALL_INDICES, body)
        buckets = result.get("aggregations", {}).get("by_province", {}).get("buckets", [])
        data = {}
        for b in buckets:
            prov = b["key"]
            if prov_list and prov not in prov_list:
                continue
            range_buckets = b["ranges"]["buckets"]
            data[prov] = [
                {
                    "range": rb["key"],
                    "count": rb["doc_count"],
                    "avg_price": round(rb["avg_price"]["value"], 2) if rb["avg_price"]["value"] else 0,
                }
                for rb in range_buckets
            ]
        return {"data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))






@router.get("/api/stats/price-distribution")
def price_distribution(
    province: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    unit: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
):
    must_clauses = []
    filter_clauses = []

    if category:
        filter_clauses.append({"term": {"category": category}})

    if keyword:
        kw_len = len(keyword)
        if kw_len <= 2:
            must_clauses.append({
                "bool": {
                    "should": [
                        {"match": {"breed": keyword}},
                        {"match": {"breed": {"query": keyword, "fuzziness": "AUTO", "boost": 5}}}
                    ]
                }
            })
        else:
            must_clauses.append({
                "bool": {
                    "should": [
                        {"match_phrase": {"breed": {"query": keyword, "boost": 20}}},
                        {"match": {"breed": {"query": keyword, "operator": "and", "minimum_should_match": "100%", "boost": 10}}}
                    ]
                }
            })
    if province:
        filter_clauses.append({"term": {"province": province}})
    if city:
        filter_clauses.append({"term": {"city": city}})
    if unit:
        filter_clauses.append({"term": {"unit": unit}})

    query = _build_bool_query(must_clauses, filter_clauses)

    body = {
        "query": query,
        "size": 0,
        "aggs": {
            "ranges": {
                "range": {
                    "field": "price",
                    "ranges": [
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
                },
                "aggs": {
                    "avg_price": {"avg": {"field": "price"}}
                }
            }
        }
    }
    try:
        result = safe_search(es, ALL_INDICES, body)
        buckets = result.get("aggregations", {}).get("ranges", {}).get("buckets", [])
        return {
            "data": [
                {
                    "range": b["key"],
                    "count": b["doc_count"],
                    "avg_price": round(b["avg_price"]["value"], 2) if b["avg_price"]["value"] else 0,
                }
                for b in buckets
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



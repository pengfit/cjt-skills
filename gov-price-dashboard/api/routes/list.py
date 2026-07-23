"""/list 页专用路由组：/api/list/*  全部走 LIST_INDICES（DWS 层）。

- /api/list/search            ← 列表搜索（DWS）
- /api/list/categories        ← 类别树聚合（DWS）
- /api/list/filter-options    ← 省份/城市/区县下拉（DWS，含 provinces）

设计初衷（2026-07-23）：
  /list 页 + 更多筛选的省份/城市/区县下拉要来自 DWS 层；
  且该页所有请求加 /api/list/ 前缀以区分其他页面（NORM/ALL_INDICES）。
  其他页面（cockpit/distribution 等）仍走 /api/* 原接口。
"""
from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from api.helpers import _build_bool_query, safe_search
from api.dependencies import es, LIST_INDICES

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────
# /api/list/filter-options  — 省份/城市/区县下拉（DWS）
# ─────────────────────────────────────────────────────────────────────
@router.get("/api/list/filter-options")
def list_filter_options():
    """返回 /list 页省份/城市/区县下拉数据（聚合 DWS）。

    返回结构：
      {
        "provinces": [{"key": "陕西", "count": 12345}, ...],
        "cities": [{"key": "西安市", "count": 5678, "province": "陕西"}, ...],
        "counties": [{"key": "雁塔区", "count": 890, "province": "陕西", "city": "西安市"}, ...],
        "provinceCityMap": {"陕西": [{"key": "西安市", "count": 5678}, ...], ...},
        "empty": bool, "message": "..."
      }
    """
    if not LIST_INDICES:
        return {
            "provinces": [], "cities": [], "counties": [], "provinceCityMap": {},
            "empty": True, "message": "LIST_INDICES（DWS）为空，请先确认 DWD→DWS ETL 已运行",
        }
    try:
        body = {
            "size": 0,
            "aggs": {
                "by_province": {
                    "terms": {"field": "province", "size": 50, "order": {"_count": "desc"}},
                    "aggs": {
                        "cities": {
                            "terms": {"field": "city", "size": 200},
                            "aggs": {
                                "counties": {
                                    "terms": {"field": "county", "size": 200}
                                }
                            }
                        }
                    }
                }
            }
        }
        agg = safe_search(es, LIST_INDICES, body)

        province_list = []
        city_list = []
        county_list = []
        province_city_map = {}

        for pb in agg.get("aggregations", {}).get("by_province", {}).get("buckets", []):
            prov = pb["key"]
            province_list.append({"key": prov, "count": pb["doc_count"]})
            province_city_map[prov] = []
            for cb in pb.get("cities", {}).get("buckets", []):
                city_key = cb["key"]
                if not city_key:
                    continue
                city_list.append({"key": city_key, "count": cb["doc_count"], "province": prov})
                province_city_map[prov].append({"key": city_key, "count": cb["doc_count"]})
                for tb in cb.get("counties", {}).get("buckets", []):
                    county_key = tb["key"]
                    if not county_key:
                        continue
                    county_list.append({
                        "key": county_key, "count": tb["doc_count"],
                        "province": prov, "city": city_key,
                    })

        return {
            "provinces": province_list,
            "cities": city_list,
            "counties": county_list,
            "provinceCityMap": province_city_map,
            "empty": len(province_list) == 0,
            "message": "DWS 中无业务数据，请先运行 DWD→DWS ETL" if len(province_list) == 0 else "",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"list_filter_options failed: {e}")


# ─────────────────────────────────────────────────────────────────────
# /api/list/search  — 列表搜索（DWS）
# ─────────────────────────────────────────────────────────────────────
@router.get("/api/list/search")
def list_search(
    keyword: Optional[str] = Query(None),
    province: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    county: Optional[str] = Query(None),
    unit: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    category_l1: Optional[str] = Query(None),
    category_l2: Optional[str] = Query(None),
    category_l3: Optional[str] = Query(None),
    price_min: Optional[float] = Query(None),
    price_max: Optional[float] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """/list 页搜索接口（DWS 版）。与 /api/search 走同样的索引，但带 list/ 前缀便于区分。"""
    if not LIST_INDICES:
        return {"total": 0, "page": page, "size": page_size, "pages": 0, "data": [],
                "warning": "LIST_INDICES（DWS）为空"}

    must_clauses = []
    filter_clauses = []

    if keyword:
        kw_len = len(keyword)
        if kw_len <= 2:
            must_clauses.append({"bool": {"should": [
                {"match": {"breed": keyword}},
                {"match": {"breed": {"query": keyword, "fuzziness": "AUTO", "boost": 5}}},
            ]}})
        else:
            must_clauses.append({"bool": {"should": [
                {"match_phrase": {"breed": {"query": keyword, "boost": 20}}},
                {"match": {"breed": {"query": keyword, "boost": 10}}},
            ]}})

    def _term(field: str, val: str):
        # DWS 里 province/city/county/category 都是 keyword 直接类型
        filter_clauses.append({"term": {field: val}})

    if province: _term("province", province)
    if city: _term("city", city)
    if county: _term("county", county)
    if unit: filter_clauses.append({"term": {"unit": unit}})
    if category: _term("category", category)
    if category_l1: _term("category_l1", category_l1)
    if category_l2: _term("category_l2", category_l2)
    if category_l3: _term("category_l3", category_l3)

    if price_min is not None and price_max is not None and price_min <= price_max:
        filter_clauses.append({"range": {"price": {"gte": price_min, "lte": price_max}}})
    elif price_min is not None and price_min >= 0:
        filter_clauses.append({"range": {"price": {"gte": price_min}}})
    elif price_max is not None and price_max >= 0:
        filter_clauses.append({"range": {"price": {"lte": price_max}}})

    query = _build_bool_query(must_clauses, filter_clauses)
    from_idx = (page - 1) * page_size

    body = {
        "query": query,
        "from": from_idx,
        "size": page_size,
        "sort": [
            {"period_end": {"order": "desc", "missing": "_last", "unmapped_type": "date"}},
            {"_score": {"order": "desc"}},
        ],
    }

    try:
        result = safe_search(es, LIST_INDICES, body)
        total = result["hits"]["total"]["value"]
        hits = [
            {
                "id": h["_id"],
                "breed": h["_source"].get("breed", ""),
                "category": h["_source"].get("category", ""),
                "spec": h["_source"].get("spec", ""),
                "attr": h["_source"].get("attr", {}),
                "unit": h["_source"].get("unit", ""),
                "price": h["_source"].get("price"),
                "price_t": h["_source"].get("price_t"),
                "price_unit": h["_source"].get("unit", ""),
                "tax_price": h["_source"].get("tax_price"),
                "province": h["_source"].get("province", ""),
                "city": h["_source"].get("city", ""),
                "county": h["_source"].get("county", ""),
                "date": h["_source"].get("update_date", ""),
                "avg_price": 0,
                "prev_price": 0,
            }
            for h in result["hits"]["hits"]
        ]
        return {
            "total": total, "page": page, "size": page_size,
            "pages": (total + page_size - 1) // page_size,
            "data": hits,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"list_search failed: {e}")


# ─────────────────────────────────────────────────────────────────────
# /api/list/categories  — 类别列表（DWS）
# ─────────────────────────────────────────────────────────────────────
@router.get("/api/list/categories")
def list_categories(size: int = Query(500, ge=1, le=500)):
    """返回 /list 页类别列表（聚合 DWS 索引）。"""
    if not LIST_INDICES:
        return {"data": [], "warning": "LIST_INDICES（DWS）为空"}
    try:
        body = {
            "size": 0,
            "aggs": {
                "categories": {
                    "terms": {"field": "category", "size": size}
                }
            }
        }
        result = safe_search(es, LIST_INDICES, body)
        buckets = result.get("aggregations", {}).get("categories", {}).get("buckets", [])
        return {
            "data": [{"key": b["key"], "count": b["doc_count"]} for b in buckets]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"list_categories failed: {e}")

"""搜索 / 分类树 / 筛选选项 路由。

- /api/search              ← /list 页用的搜索接口（走 DWS via LIST_INDICES）
- /api/taxonomy/v3/tree    ← L1→L2→L3 分类树（读 breed_canonical.db）
- /api/filter-options      ← 省份/城市/区县/期号列表（聚合 NORM）

路由都加在 router 上，main.py 里 `app.include_router(router, **_PROTECTED)`。
"""
from __future__ import annotations
import os
import sqlite3
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from elasticsearch import NotFoundError, RequestError, ConnectionError as ESConnectionError, ConnectionTimeout

from api.helpers import _build_bool_query, safe_search
from api.dependencies import es, LIST_INDICES, ALL_INDICES, NORM_INDICES
from api.paths import CATEGORY_DB

router = APIRouter()


@router.get("/api/search")
def search(
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
    must_clauses = []
    filter_clauses = []

    if keyword:
        kw_len = len(keyword)
        if kw_len <= 2:
            # 短词（≤2字符）：精确 keyword 匹配 + 宽松 fuzzy 容错
            must_clauses.append({
                "bool": {
                    "should": [
                        {"match": {"breed": keyword}},
                        {"match": {"breed": {"query": keyword, "fuzziness": "AUTO", "boost": 5}}},
                    ]
                }
            })
        else:
            # 较长词（≥3字符）：match_phrase 精确匹配 + match 宽松匹配
            must_clauses.append({
                "bool": {
                    "should": [
                        {"match_phrase": {"breed": {"query": keyword, "boost": 20}}},
                        {"match": {"breed": {"query": keyword, "boost": 10}}},
                    ]
                }
            })
    if province:
        filter_clauses.append({"term": {"province": province}})
    if city:
        filter_clauses.append({"term": {"city": city}})
    if county:
        filter_clauses.append({"term": {"county": county}})
    if unit:
        filter_clauses.append({"term": {"unit": unit}})
    if category:
        filter_clauses.append({"term": {"category": category}})
    if category_l1:
        filter_clauses.append({"term": {"category_l1": category_l1}})
    if category_l2:
        filter_clauses.append({"term": {"category_l2": category_l2}})
    if category_l3:
        filter_clauses.append({"term": {"category_l3": category_l3}})
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
        "aggs": {},
    }

    try:
        # 2026-07-23: /list 页单独走 DWS（其他页面仍走 NORM）
        result = safe_search(es, LIST_INDICES, body)
        total = result["hits"]["total"]["value"]

        # avg_price_map and prev_price_map removed - multi-index has inconsistent field types

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
            "total": total,
            "page": page,
            "size": page_size,
            "pages": (total + page_size - 1) // page_size,
            "data": hits,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/taxonomy/v3/tree")
def taxonomy_v3_tree():
    """返回 L1→L2→L3 分类树（纯分类体系，无 ES 计数）"""
    db_path = CATEGORY_DB
    if not os.path.isfile(db_path):
        return {"ok": False, "error": f"分类库不存在: {db_path}", "tree": []}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT l1, name_l1, l2, name_l2, l3, name_l3 "
            "FROM category_v3 WHERE l4 = 'UNCLASSIFIED' "
            "ORDER BY l1, l2, l3"
        ).fetchall()
        conn.close()
    except Exception as e:
        return {"ok": False, "error": str(e), "tree": []}

    # 组装树
    tree = []
    l1_map = {}
    for l1, name_l1, l2, name_l2, l3, name_l3 in rows:
        if l1 not in l1_map:
            node = {"l1": l1, "name_l1": name_l1, "children": []}
            l1_map[l1] = node
            tree.append(node)
        l1_node = l1_map[l1]
        l2_node = None
        for c in l1_node["children"]:
            if c["l2"] == l2:
                l2_node = c
                break
        if not l2_node:
            l2_node = {"l2": l2, "name_l2": name_l2, "children": []}
            l1_node["children"].append(l2_node)
        l2_node["children"].append({
            "l3": l3, "name_l3": name_l3,
        })

    return {"ok": True, "tree": tree}
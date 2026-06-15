from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from elasticsearch import Elasticsearch
from typing import Optional
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ES_HOST = os.environ.get("ES_HOST", "http://localhost:59200")
ES_INDEX = os.environ.get("ES_INDEX", "dwd_xian_price")
ALL_INDICES = "dws_xian_price,dws_sichuan_price,dws_chongqing_price,dws_jinan_price,dws_rizhao_price,dws_heze_price,dws_henan_price"

app = FastAPI(title="材价通 API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from api.routes.provenance import router as provenance_router
app.include_router(provenance_router)

es = Elasticsearch([ES_HOST])


def _build_bool_query(must_clauses, filter_clauses):
    """构建 bool 查询，处理空列表情况"""
    must_clause = must_clauses if must_clauses else [{"match_all": {}}]
    if filter_clauses:
        return {"bool": {"must": must_clause, "filter": filter_clauses}}
    return {"bool": {"must": must_clause}}


@app.get("/")
def root():
    return {"message": "材价通 API", "version": "1.0.0"}


@app.get("/api/search")
def search(
    keyword: Optional[str] = Query(None),
    province: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    county: Optional[str] = Query(None),
    unit: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    category_system: Optional[str] = Query(None),
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
    if price_min is not None and price_max is not None and price_min <= price_max:
        filter_clauses.append({"range": {"price": {"gte": price_min, "lte": price_max}}})
    elif price_min is not None and price_min >= 0:
        filter_clauses.append({"range": {"price": {"gte": price_min}}})
    elif price_max is not None and price_max >= 0:
        filter_clauses.append({"range": {"price": {"lte": price_max}}})

    if category_system:
        # 直接用 ES 存储的 code 值（不转 cat_sys_map 映射）
        # 背景：cat_sys_map 是 cat_name→sys_name 反向映射，不适用于 ES code 字段
        # ES 存的就是 STEEL_METAL/PLUMBING 等 code，前端传也是 code
        filter_clauses.append({"term": {"category_system": category_system}})

    query = _build_bool_query(must_clauses, filter_clauses)
    from_idx = (page - 1) * page_size

    body = {
        "query": query,
        "from": from_idx,
        "size": page_size,
        "sort": [{"_score": {"order": "desc"}}],
        "aggs": {}
    }

    try:
        result = es.search(index=ALL_INDICES, body=body)
        total = result["hits"]["total"]["value"]

        # avg_price_map and prev_price_map removed - multi-index has inconsistent field types

        hits = [
            {
                "id": h["_id"],
                "breed": h["_source"].get("breed", ""),
                "category": h["_source"].get("category", ""),
                # 直接读 ES 存储的 category_system 字段（不转 cat_sys_map 反向映射）
                # 背景：cat_sys_map 是 cat_name→sys_name 反向映射，"其他" 文档会返空字符串
                "category_system": h["_source"].get("category_system", ""),
                # 同上：直接读 ES category_system_name（ETL 阶段已填中文名）
                "category_system_name": h["_source"].get("category_system_name", ""),
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
            "data": hits
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/overview")
def overview(
    keyword: Optional[str] = Query(None),
    province: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    unit: Optional[str] = Query(None),
):
    must_clauses = []
    filter_clauses = []

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
            "provinces": {"cardinality": {"field": "province"}},
            "cities": {"cardinality": {"field": "city"}},
            "avg_price": {"avg": {"field": "price"}},
            "max_price": {"max": {"field": "price"}},
            "min_price": {"min": {"field": "price"}},
            "by_province": {
                "terms": {"field": "province", "size": 30},
                "aggs": {
                    "avg_price": {"avg": {"field": "price"}},
                    "count": {"value_count": {"field": "price"}}
                }
            },
            "by_category": {
                "terms": {"field": "category", "size": 30, "order": {"_count": "desc"}},
                "aggs": {
                    "avg_price": {"avg": {"field": "price"}},
                    "count": {"value_count": {"field": "price"}},
                    # sub-agg 拿 category_system（ES 存的 code）让 /api/stats/overview 返 ES 实际值
                    "sys": {"terms": {"field": "category_system", "size": 1}},
                    # 同上：拿 category_system_name（ETL 阶段已填中文名）
                    "sys_name": {"terms": {"field": "category_system_name", "size": 1}}
                }
            }
        }
    }
    try:
        # 用 _count API 获取真实总数
        total_result = es.count(index=ALL_INDICES, body={"query": query})
        total_docs = total_result["count"]

        result = es.search(index=ALL_INDICES, body=body)
        aggs = result["aggregations"]
        province_buckets = aggs["by_province"]["buckets"]
        return {
            "total_docs": total_docs,
            "total_provinces": aggs["provinces"]["value"],
            "total_cities": aggs["cities"]["value"],
            "avg_price": round(aggs["avg_price"]["value"], 2) if aggs["avg_price"]["value"] else 0,
            "max_price": aggs["max_price"]["value"] or 0,
            "min_price": aggs["min_price"]["value"] or 0,
            "by_province": [
                {
                    "province": b["key"],
                    "count": b["count"]["value"],
                    "avg_price": round(b["avg_price"]["value"], 2) if b["avg_price"]["value"] else 0
                }
                for b in province_buckets
            ],
            "by_category": [
                {"category": b["key"], "count": b["count"]["value"],
                 "avg_price": round(b["avg_price"]["value"], 2) if b["avg_price"]["value"] else 0,
                 # 直接读 sub-agg 拿 ES 存的 category_system（不转 cat_sys_map）
                 "category_system": b.get("sys", {}).get("buckets", [{}])[0].get("key", "") if b.get("sys", {}).get("buckets") else "",
                 # 同上：直接读 sub-agg 拿 ES 存的 category_system_name
                 "category_system_name": b.get("sys_name", {}).get("buckets", [{}])[0].get("key", "") if b.get("sys_name", {}).get("buckets") else ""}
                for b in aggs.get("by_category", {}).get("buckets", [])
            ],
            "categories": [b["key"] for b in aggs.get("by_category", {}).get("buckets", [])]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/filter-options")
def filter_options():
    try:
        province_city_agg = es.search(index=ALL_INDICES, size=0, aggs={
            "by_province": {
                "terms": {"field": "province", "size": 50, "order": {"_count": "desc"}},
                "aggs": {
                    "cities": {
                        "terms": {"field": "city", "size": 100},
                        "aggs": {
                            "counties": {
                                "terms": {"field": "county", "size": 100}
                            }
                        }
                    }
                }
            }
        })
        city_list = []
        county_list = []
        province_city_map = {}

        for pb in province_city_agg["aggregations"]["by_province"]["buckets"]:
            prov = pb["key"]
            province_city_map[prov] = []
            for cb in pb["cities"]["buckets"]:
                city_key = cb["key"]
                if city_key:
                    city_list.append({"key": city_key, "count": cb["doc_count"], "province": prov})
                    province_city_map[prov].append({"key": city_key, "count": cb["doc_count"]})
                for tb in cb["counties"]["buckets"]:
                    county_key = tb["key"]
                    if county_key:
                        county_list.append({"key": county_key, "count": tb["doc_count"], "province": prov, "city": city_key})

        return {
            "cities": city_list,
            "counties": county_list,
            "provinceCityMap": province_city_map,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/province-ranges")
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
        result = es.search(index=ALL_INDICES, body=body)
        buckets = result["aggregations"]["by_province"]["buckets"]
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


@app.get("/api/stats/price-distribution")
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
        result = es.search(index=ALL_INDICES, body=body)
        buckets = result["aggregations"]["ranges"]["buckets"]
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


@app.get("/api/stats/categories")
def stats_categories(size: int = Query(100, ge=1, le=500)):
    """返回所有产品类别及数据量"""
    try:
        body = {
            "size": 0,
            "aggs": {
                "categories": {
                    "terms": {"field": "category", "size": size}
                }
            }
        }
        result = es.search(index=ALL_INDICES, body=body)
        buckets = result["aggregations"]["categories"]["buckets"]
        return {
            "data": [
                {"key": b["key"], "count": b["doc_count"]}
                for b in buckets
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/breed-category-rules")
def stats_breed_category_rules(
    distinct_categories: int = Query(0, ge=0, le=1),
    breed_size: int = Query(500, ge=1, le=5000),
    category_size: int = Query(100, ge=1, le=500),
):
    """返回全量 breed 及其归属分类，用于分类规则库下拉列表
    - distinct_categories=1: 只返回归属于单一分类的 breed
    """
    try:
        body = {
            "size": 0,
            "aggs": {
                "breeds": {
                    "terms": {"field": "breed.keyword", "size": breed_size},
                    "aggs": {
                        "categories": {
                            "terms": {"field": "category.keyword", "size": category_size}
                        }
                    }
                }
            }
        }
        result = es.search(index=ALL_INDICES, body=body)
        buckets = result["aggregations"]["breeds"]["buckets"]

        items = []
        for b in buckets:
            cats = b["categories"]["buckets"]
            cat_count = len(cats)
            # 取文档数最多的分类作为主分类
            primary_cat = cats[0]["key"] if cats else "其他"
            item = {
                "breed": b["key"],
                "category": primary_cat,
                "category_count": cat_count,
                "doc_count": b["doc_count"],
                "categories": [c["key"] for c in cats],
            }
            if distinct_categories == 1:
                if cat_count == 1:
                    items.append(item)
            else:
                items.append(item)

        return {"data": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/category-detail")
def stats_category_detail(
    category: str = Query(...),
    province_limit: int = Query(20, ge=1, le=50),
    breed_limit: int = Query(20, ge=1, le=100),
):
    """返回指定类别的省份分布、热门品种"""
    try:
        body = {
            "query": {"term": {"category": category}},
            "size": 0,
            "aggs": {
                "avg_price": {"avg": {"field": "price"}},
                "max_price": {"max": {"field": "price"}},
                "provinces": {
                    "terms": {"field": "province", "size": province_limit}
                },
                "breeds": {
                    "terms": {"field": "breed.keyword", "size": breed_limit},
                    "aggs": {
                        "province": {"terms": {"field": "province", "size": 1}},
                        "specs": {"terms": {"field": "spec.keyword", "size": 3}},
                        "units": {
                            "terms": {"field": "unit", "size": 10},
                            "aggs": {
                                "avg_price": {"avg": {"field": "price"}},
                                "min_price": {"min": {"field": "price"}},
                                "max_price": {"max": {"field": "price"}},
                                "cnt": {"value_count": {"field": "price"}}
                            }
                        }
                    }
                },
                "breed_count": {
                    "cardinality": {"field": "breed.keyword"}
                }
            }
        }
        result = es.search(index=ALL_INDICES, body=body)
        aggs = result["aggregations"]

        provinces = [
            {"key": b["key"], "count": b["doc_count"]}
            for b in aggs["provinces"]["buckets"]
        ]

        breeds = []
        for b in aggs["breeds"]["buckets"]:
            unit_buckets = b["units"]["buckets"]
            if unit_buckets:
                primary = unit_buckets[0]
                avg_price = round(primary["avg_price"]["value"], 2) if primary["avg_price"]["value"] else 0
                min_price = round(primary["min_price"]["value"], 2) if primary["min_price"]["value"] else 0
                max_price = round(primary["max_price"]["value"], 2) if primary["max_price"]["value"] else 0
                unit_fixed = primary["key"]
            else:
                avg_price = min_price = max_price = 0
                unit_fixed = ""
            breeds.append({
                "key": b["key"],
                "count": b["doc_count"],
                "province": b["province"]["buckets"][0]["key"] if b["province"]["buckets"] else "",
                "avg_price": avg_price,
                "min_price": min_price,
                "max_price": max_price,
                "unit": unit_fixed,
                "specs": [s["key"] for s in b["specs"]["buckets"]],
            })

        return {
            "data": {
                "avg_price": round(aggs["avg_price"]["value"], 2) if aggs["avg_price"]["value"] else 0,
                "max_price": round(aggs["max_price"]["value"], 2) if aggs["max_price"]["value"] else 0,
                "provinces": provinces,
                "breeds": breeds,
                "breed_count": aggs["breed_count"]["value"],
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/category-price-ranges")
def category_price_ranges(category: str = Query(...)):
    """返回指定类别的动态价格区间，按分位数分为5段，每段覆盖约20%数据"""
    try:
        # Get percentiles to build equal-frequency ranges
        stats_body = {
            "query": {"term": {"category": category}},
            "size": 0,
            "aggs": {
                "min_price": {"min": {"field": "price"}},
                "max_price": {"max": {"field": "price"}},
                "avg_price": {"avg": {"field": "price"}},
                "price_percentiles": {
                    "percentiles": {
                        "field": "price",
                        "percents": [15, 35, 50, 65, 85]
                    }
                }
            }
        }
        stats_result = es.search(index=ALL_INDICES, body=stats_body)
        aggs = stats_result["aggregations"]
        min_p = aggs["min_price"]["value"] or 0
        max_p = aggs["max_price"]["value"] or 0
        avg_p = aggs["avg_price"]["value"] or 0

        if max_p <= 0:
            return {"data": [], "stats": {"min": 0, "max": 0, "avg": 0}}

        vals = aggs["price_percentiles"]["values"]
        def pct(key):
            key_str = str(key)
            key_float = float(key)
            if key_str in vals:
                return float(vals[key_str])
            for k, v in vals.items():
                if abs(float(k) - key_float) < 0.01:
                    return float(v)
            raise KeyError(key)
        t1 = pct(15.0)
        t2 = pct(35.0)
        t3 = pct(50.0)
        t4 = pct(65.0)
        t5 = pct(85.0)

        def round100(v): return float(round(v / 100) * 100)

        r0 = min_p
        r1 = round100(t1)
        r2 = round100(t2)
        r3 = round100(t3)
        r4 = round100(t4)
        r5 = round100(t5)
        r6 = max_p

        # Avoid zero-width or inverted ranges
        if r1 <= r0: r1 = r0 + 100
        if r2 <= r1: r2 = r1 + 100
        if r3 <= r2: r3 = r2 + 100
        if r4 <= r3: r4 = r3 + 100
        if r5 <= r4: r5 = r4 + 100

        def fmt(lo, hi):
            def k_str(v):
                if v >= 10000:
                    return f"{int(v/1000)}k"
                elif v >= 1000:
                    if v % 1000 == 0:
                        return f"{int(v/1000)}k"
                    return str(int(v))
                else:
                    return str(int(v))
            return f"{k_str(lo)}-{k_str(hi)}"

        def fmt_single(v):
            if v >= 10000:
                return f"{int(v/1000)}k"
            elif v >= 1000:
                if v % 1000 == 0:
                    return f"{int(v/1000)}k"
                return str(int(v))
            else:
                return str(int(v))

        ranges_config = [
            {"key": "远低于均价", "from": r0, "to": r1},
            {"key": "低于均价",   "from": r1,  "to": r2},
            {"key": "接近均价",   "from": r2,  "to": r3},
            {"key": "高于均价",   "from": r3,  "to": r4},
            {"key": "远高于均价", "from": r4,  "to": r5 + 1},
        ]

        body = {
            "query": {"match_all": {}},
            "size": 0,
            "aggs": {
                "ranges": {
                    "range": {
                        "field": "price",
                        "ranges": ranges_config
                    },
                    "aggs": {
                        "avg_price": {"avg": {"field": "price"}}
                    }
                }
            }
        }
        result = es.search(index=ALL_INDICES, body=body)
        buckets = result["aggregations"]["ranges"]["buckets"]

        data = []
        for b in buckets:
            from_val = b["from"]
            to_val = b["to"]
            is_last = (b["key"] == "远高于均价")
            if is_last:
                label = "> " + fmt_single(from_val)
            else:
                label = fmt(from_val, to_val)
            data.append({
                "range": label,
                "desc": b["key"],
                "count": b["doc_count"],
                "avg_price": round(b["avg_price"]["value"], 2) if b["avg_price"]["value"] else 0,
            })

        return {
            "data": data,
            "stats": {
                "min": round(min_p, 2),
                "max": round(max_p, 2),
                "avg": round(avg_p, 2),
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/category-breeds")
def stats_category_breeds(
    category: str = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """返回指定类别的去重品种列表（分页），按标准单位分层聚合"""
    try:
        body = {
            "query": {"term": {"category": category}},
            "size": 0,
            "aggs": {
                "all_breeds": {
                    "terms": {"field": "breed.keyword", "size": 10000},
                    "aggs": {
                        "province": {"terms": {"field": "province", "size": 1}},
                        "specs": {"terms": {"field": "spec.keyword", "size": 3}},
                        "units": {
                            "terms": {"field": "unit", "size": 10},
                            "aggs": {
                                "avg_price": {"avg": {"field": "price"}},
                                "min_price": {"min": {"field": "price"}},
                                "max_price": {"max": {"field": "price"}},
                                "cnt": {"value_count": {"field": "price"}}
                            }
                        }
                    }
                }
            }
        }
        result = es.search(index=ALL_INDICES, body=body)
        aggs = result["aggregations"]
        all_buckets = aggs["all_breeds"]["buckets"]

        start = (page - 1) * page_size
        end = start + page_size
        page_buckets = all_buckets[start:end]

        breeds = []
        for b in page_buckets:
            # 按 unit_fixed 分组，取最大计数量的单位组作为主价格
            unit_buckets = b["units"]["buckets"]
            if unit_buckets:
                primary = unit_buckets[0]  # 按 doc_count 排序，第一位数量最多
                avg_price = round(primary["avg_price"]["value"], 2) if primary["avg_price"]["value"] else 0
                min_price = round(primary["min_price"]["value"], 2) if primary["min_price"]["value"] else 0
                max_price = round(primary["max_price"]["value"], 2) if primary["max_price"]["value"] else 0
                unit_fixed = primary["key"]
            else:
                avg_price = min_price = max_price = 0
                unit_fixed = ""

            breeds.append({
                "key": b["key"],
                "count": b["doc_count"],
                "province": b["province"]["buckets"][0]["key"] if b["province"]["buckets"] else "",
                "avg_price": avg_price,
                "min_price": min_price,
                "max_price": max_price,
                "unit": unit_fixed,
                "specs": [s["key"] for s in b["specs"]["buckets"]],
            })

        return {
            "data": breeds,
            "total": len(all_buckets),
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/breed-detail")
def stats_breed_detail(
    category: str = Query(...),
    breed: str = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """返回指定品种的详细规格价格分析（按单位→规格分层聚合）"""
    try:
        body = {
            "query": {
                "bool": {
                    "filter": [
                        {"term": {"breed.keyword": breed}}
                    ]
                }
            },
            "size": 0,
            "aggs": {
                "by_unit": {
                    "terms": {
                        "script": {
                            "source": "def u = doc['unit'].value; return (u != null && u.length() > 0 && u != '/') ? u : '/';",
                            "lang": "painless"
                        },
                        "size": 20
                    },
                    "aggs": {
                        "cnt": {"value_count": {"field": "price"}},
                        "avg_p": {"avg": {"field": "price"}},
                        "by_spec": {
                            "terms": {"field": "spec.keyword", "size": 200},
                            "aggs": {
                                "cnt": {"value_count": {"field": "price"}},
                                "avg_p": {"avg": {"field": "price"}},
                                "min_p": {"min": {"field": "price"}},
                                "max_p": {"max": {"field": "price"}},
                                "by_prov": {"terms": {"field": "province", "size": 1}}
                            }
                        }
                    }
                }
            }
        }
        result = es.search(index=ALL_INDICES, body=body)
        aggs = result["aggregations"]
        units_data = []
        for ub in aggs["by_unit"]["buckets"]:
            unit_key = ub["key"]
            specs_data = []
            spec_buckets = ub["by_spec"]["buckets"]

            # Pagination within specs
            start = (page - 1) * page_size
            end = start + page_size
            page_specs = spec_buckets[start:end]

            for sb in page_specs:
                prov = sb["by_prov"]["buckets"][0]["key"] if sb["by_prov"]["buckets"] else ""
                avg_v = sb["avg_p"]["value"]
                min_v = sb["min_p"]["value"]
                max_v = sb["max_p"]["value"]
                specs_data.append({
                    "key": sb["key"],
                    "count": sb["cnt"]["value"],
                    "avg_price": round(avg_v, 2) if avg_v else 0,
                    "min_price": round(min_v, 2) if min_v else 0,
                    "max_price": round(max_v, 2) if max_v else 0,
                    "province": prov
                })

            unit_avg = ub["avg_p"]["value"]
            units_data.append({
                "key": unit_key,
                "count": ub["cnt"]["value"],
                "avg_price": round(unit_avg, 2) if unit_avg else 0,
                "specs": specs_data,
                "spec_total": len(spec_buckets),
                "page": page,
                "page_size": page_size
            })

        total_records = sum(u["count"] for u in units_data)

        return {
            "data": {
                "breed": breed,
                "category": category,
                "total_records": result["hits"]["total"]["value"],
                "units": units_data
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stats/data-health")
def stats_data_health():
    """数据健康度监控：每日数据量、各省份最新日期、增量异常检测"""
    try:
        # 1. 每日数据量（最近30天）
        daily_body = {
            "size": 0,
            "query": {"range": {"update_date": {"gte": "now-30d"}}},
            "aggs": {
                "daily": {
                    "date_histogram": {"field": "date", "calendar_interval": "day"},
                    "aggs": {"count": {"value_count": {"field": "price"}}}
                }
            }
        }
        daily_result = es.search(index=ALL_INDICES, body=daily_body)
        daily_buckets = daily_result["aggregations"]["daily"]["buckets"]
        daily_data = [
            {"date": b["key_as_string"][:10], "count": b["doc_count"]}
            for b in daily_buckets
        ]

        # 2. 各省份最新数据日期
        province_body = {
            "size": 0,
            "aggs": {
                "by_province": {
                    "terms": {"field": "province", "size": 30},
                    "aggs": {
                        "max_date": {"max": {"field": "date"}},
                        "count": {"value_count": {"field": "price"}}
                    }
                }
            }
        }
        province_result = es.search(index=ALL_INDICES, body=province_body)
        province_buckets = province_result["aggregations"]["by_province"]["buckets"]

        # 计算数据新鲜度阈值（7天）
        import datetime
        threshold = datetime.datetime.now() - datetime.timedelta(days=7)
        provinces_data = []
        stale_count = 0
        for b in province_buckets:
            max_date_str = b.get("max_date", {}).get("value_as_string", "")[:10]
            is_stale = False
            if max_date_str:
                try:
                    max_date = datetime.datetime.strptime(max_date_str, "%Y-%m-%d")
                    is_stale = max_date < threshold
                    if is_stale:
                        stale_count += 1
                except Exception:
                    pass
            provinces_data.append({
                "province": b["key"],
                "latest_date": max_date_str,
                "count": b["doc_count"],
                "is_stale": is_stale,
            })
        provinces_data.sort(key=lambda x: x["latest_date"], reverse=True)

        # 3. 总览
        # Use ES _count API for accurate total (bypasses 10000 hit cap)
        try:
            count_resp = es.count(index=ALL_INDICES)
            total_count = count_resp["count"]
        except Exception:
            # Fallback: use match_all with track_total=true
            total_body = {"query": {"match_all": {}}, "size": 0, "track_total": True}
            total_result = es.search(index=ALL_INDICES, body=total_body)
            total_count = total_result["hits"]["total"]["value"]

        # 4. 增量异常检测：最近7天 vs 前7天（改为并发请求）
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            recent_future = pool.submit(
                es.count, index=ALL_INDICES,
                body={"query": {"range": {"update_date": {"gte": "now-7d"}}}}
            )
            prev_future = pool.submit(
                es.count, index=ALL_INDICES,
                body={"query": {"range": {"update_date": {"gte": "now-14d", "lt": "now-7d"}}}}
            )
            cat_body = {"size": 0, "aggs": {"by_category": {"terms": {"field": "category", "size": 20}, "aggs": {"count": {"value_count": {"field": "price"}}}}}}
            cat_future = pool.submit(es.search, index=ALL_INDICES, body=cat_body)
        recent_count = recent_future.result()["count"]
        prev_count = prev_future.result()["count"]
        cat_result = cat_future.result()
        inc_ratio = round((recent_count / prev_count * 100) - 100, 1) if prev_count else 0
        cat_buckets = cat_result["aggregations"]["by_category"]["buckets"]
        cat_data = [{"category": b["key"], "count": b["doc_count"]} for b in cat_buckets]

        return {
            "total_docs": total_count,
            "province_count": len(provinces_data),
            "stale_provinces": stale_count,
            "recent_7d_vs_prev_7d_pct": inc_ratio,
            "recent_7d_count": recent_count,
            "prev_7d_count": prev_count,
            "daily": daily_data,
            "provinces": provinces_data,
            "categories": cat_data,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _get_county_sync_details(es, es_index="ods_material_xian_price"):
    """从 material_xian_price 按区县聚合，返回各区县同步状态"""
    ALL_COUNTIES = ["阎良区", "临潼区", "高陵区", "鄠邑区", "蓝田县", "周至县"]
    try:
        body = {
            "size": 0,
            "aggs": {
                "by_county": {
                    "terms": {"field": "county", "size": 20},
                    "aggs": {
                        "max_date": {"max": {"field": "update_date"}},
                        "min_date": {"min": {"field": "update_date"}},
                        "min_create": {"min": {"field": "create_time"}},
                        "max_create": {"max": {"field": "create_time"}},
                        "count": {"value_count": {"field": "price"}}
                    }
                }
            }
        }
        res = es.search(index=es_index, body=body)
        buckets = res.get("aggregations", {}).get("by_county", {}).get("buckets", [])
        county_map = {}
        for b in buckets:
            max_d = b.get("max_date", {}).get("value_as_string", "")[:10]
            min_d = b.get("min_date", {}).get("value_as_string", "")[:10]
            county_map[b["key"]] = {
                "county": b["key"],
                "doc_count": b["doc_count"],
                "es_max_date": max_d or min_d,
                "es_min_date": min_d,
                "es_max_create": b.get("max_create", {}).get("value_as_string", "")[:19] if b.get("max_create", {}).get("value_as_string") else None,
                "status": "ok"
            }
        # Fill missing counties as never synced
        for c in ALL_COUNTIES:
            if c not in county_map:
                county_map[c] = {"county": c, "doc_count": 0, "es_max_date": None, "es_min_date": None, "status": "not_synced"}
        return list(county_map.values())
    except Exception:
        return [{"county": c, "doc_count": 0, "es_max_date": None, "status": "error"} for c in ALL_COUNTIES]

@app.get("/api/stats/xian-sync-progress")
def stats_xian_sync_progress():
    """西安工程造价信息同步进度（每个区县一条记录）"""
    try:
        PROGRESS_INDEX = "ods_material_xian_price_sync_progress"

        # 增量检测：ES 最新 update_date
        es_latest = None
        try:
            es_res = es.search(index="ods_material_xian_price", body={
                "size": 1, "sort": [{"update_date": "desc"}], "_source": ["update_date"]
            })
            es_hits = es_res.get("hits", {}).get("hits", [])
            if es_hits:
                es_latest = es_hits[0]["_source"].get("update_date", "")[:10]
        except Exception:
            pass

        # 配置中记录的上次同步日期
        last_sync_date = None
        try:
            cfg_path = "/Users/pengfit/.openclaw/workspace/skills/xa-material-price/config.yml"
            if os.path.exists(cfg_path):
                with open(cfg_path) as f:
                    cfg = yaml.safe_load(f)
                last_sync_date = cfg.get("sync", {}).get("last_update_date", "")
        except Exception:
            pass

        # ES 最新日期 > 配置上次同步日期 → 网站有更新
        has_incremental = False
        if es_latest and last_sync_date:
            has_incremental = es_latest > last_sync_date
        elif es_latest and not last_sync_date:
            has_incremental = True

        # 查找最新有实际区县（current_county 不为空）的记录
        latest = es.search(index=PROGRESS_INDEX, body={
            "size": 1,
            "sort": [{"last_updated": "desc"}],
            "query": {
                "bool": {
                    "must": [{"exists": {"field": "current_county"}}]
                }
            }
        })
        hits = latest.get("hits", {}).get("hits", [])
        if not hits:
            return {
                "run_id": "", "status": "", "current_county": "",
                "current_page": 0, "total_pages": 0, "total_records": 0,
                "docs_written": 0, "percent": 0, "duration_sec": 0,
                "update_date": "", "last_updated": "", "error": "",
                "completed_counties": 0, "total_counties": 6,
                "last_sync_date": last_sync_date, "es_latest": es_latest,
                "has_incremental": has_incremental,
                "spot_check_ok": None, "spot_check_details": "",
                "total_docs": 0, "county_details": []
            }

        current_src = hits[0]["_source"]
        run_id = current_src.get("run_id", "")

        # 获取该 run_id 下所有区县的记录（排除空区县 doc）
        all_records = es.search(index=PROGRESS_INDEX, body={
            "size": 20,
            "sort": [{"last_updated": "asc"}],
            "query": {
                "bool": {
                    "must": [
                        {"term": {"run_id": run_id}},
                        {"exists": {"field": "current_county"}}
                    ]
                }
            }
        })
        records = all_records.get("hits", {}).get("hits", [])

        # spot_check 结果从最新一条记录获取
        spot_ok = None
        spot_details = ""
        if hits:
            spot_ok = hits[0]["_source"].get("spot_check_ok")
            spot_details = hits[0]["_source"].get("spot_check_details", "")

        county_details = [{
            "county": r["_source"].get("current_county", ""),
            "status": r["_source"].get("status", ""),
            "current_page": r["_source"].get("current_page", 0),
            "total_pages": r["_source"].get("total_pages", 0),
            "total_records": r["_source"].get("total_records", 0),
            "docs_written": r["_source"].get("docs_written", 0),
            "doc_count": r["_source"].get("docs_written", 0),
            "percent": round(r["_source"].get("percent", 0), 2),
            "update_date": r["_source"].get("update_date", ""),
            "last_updated": r["_source"].get("last_updated", ""),
            "duration_sec": round(r["_source"].get("duration_sec", 0), 2),
        } for r in records]

        # 从 county_details 推导整体状态
        overall_status = "completed"
        current_county = ""
        for d in county_details:
            if not d["county"]:
                continue
            if d["status"] == "running":
                overall_status = "running"
                current_county = d["county"]
                break
            if d["status"] == "interrupted":
                overall_status = "interrupted"

        completed = sum(1 for d in county_details if d.get("status") == "completed")

        return {
            "run_id": run_id,
            "status": overall_status,
            "current_county": current_county,
            "current_page": current_src.get("current_page", 0),
            "total_pages": current_src.get("total_pages", 0),
            "total_records": current_src.get("total_records", 0),
            "docs_written": sum(d.get("docs_written", 0) for d in county_details),
            "percent": round(current_src.get("percent", 0), 2),
            "duration_sec": round(current_src.get("duration_sec", 0), 2),
            "update_date": current_src.get("update_date", ""),
            "last_updated": current_src.get("last_updated", ""),
            "error": current_src.get("error", ""),
            "completed_counties": completed,
            "total_counties": 6,
            "last_sync_date": last_sync_date,
            "es_latest": es_latest,
            "has_incremental": has_incremental,
            "spot_check_ok": spot_ok,
            "spot_check_details": spot_details,
            "total_docs": sum(d.get("docs_written", 0) for d in county_details),
            "county_details": county_details,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/sichuan-sync-progress")
def stats_sichuan_sync_progress():
    """四川工程造价信息同步进度"""
    try:
        PROGRESS_INDEX = "material_sichuan_price_sync_progress"

        # 查找最新有实际地区（area不为空）的记录
        latest = es.search(index=PROGRESS_INDEX, body={
            "size": 1,
            "sort": [{"last_updated": "desc"}],
            "query": {
                "bool": {
                    "must": [
                        {"exists": {"field": "area"}}
                    ]
                }
            }
        })
        hits = latest.get("hits", {}).get("hits", [])
        if not hits:
            return {"status": "", "area": "", "period": "", "current_page": 0,
                    "total_pages": 0, "docs_written": 0, "percent": 0,
                    "duration_sec": 0, "last_updated": "", "run_id": "",
                    "error": "", "total_docs": 0, "area_details": [],
                    "last_sync_period": "", "es_latest_period": "", "has_incremental": False}

        current_src = hits[0]["_source"]
        run_id = current_src.get("run_id", "")

        # 获取该 run_id 下所有地区的记录（排除空地区doc）
        all_records = es.search(index=PROGRESS_INDEX, body={
            "size": 100,
            "sort": [{"last_updated": "asc"}],
            "query": {
                "bool": {
                    "must": [
                        {"term": {"run_id": run_id}},
                        {"exists": {"field": "area"}}
                    ]
                }
            }
        })
        records = all_records.get("hits", {}).get("hits", [])
        area_details = [{
            "area": r["_source"].get("area", ""),
            "status": r["_source"].get("status", ""),
            "current_page": r["_source"].get("current_page", 0),
            "total_pages": r["_source"].get("total_pages", 0),
            "docs_written": r["_source"].get("docs_written", 0),
            "percent": round(r["_source"].get("percent", 0), 2),
            "last_updated": r["_source"].get("last_updated", ""),
            "duration_sec": round(r["_source"].get("duration_sec", 0), 2),
        } for r in records]

        total_docs = 0
        try:
            count_res = es.count(index="material_sichuan_price")
            total_docs = count_res.get("count", 0)
        except Exception:
            pass

        # 从 area_details 确定当前活动地区和整体状态（跳过空地区记录）
        current_area = ""
        overall_status = "completed"
        for d in area_details:
            if not d["area"]:  # 跳过空地区占位记录
                continue
            if d["status"] == "running":
                overall_status = "running"
                current_area = d["area"]
                break
            if d["status"] == "interrupted":
                overall_status = "interrupted"
            # 正在进行中（页码未满）覆盖"已完成"状态
            if d["status"] == "completed" and d.get("current_page", 0) < d.get("total_pages", 0):
                overall_status = "running"
                current_area = d["area"]
                break


        # 增量检测：从 sichuan-price config 读取 last_period，从 ES 读取最新 period
        last_sync_period = ""
        es_latest_period = ""
        has_new_period = False
        try:
            cfg_path = "/Users/pengfit/.openclaw/workspace/skills/sichuan-price/config.yml"
            if os.path.exists(cfg_path):
                with open(cfg_path, 'r', encoding='utf-8') as f:
                    cfg = yaml.safe_load(f)
                last_sync_period = cfg.get('sync', {}).get('last_period', '') or ''
        except Exception:
            pass
        try:
            es_res = es.search(index="material_sichuan_price", body={
                "size": 1,
                "sort": [{"update_date": "desc"}],
                "_source": ["period"]
            })
            es_hits = es_res.get("hits", {}).get("hits", [])
            if es_hits:
                es_latest_period = es_hits[0]["_source"].get("period", "") or ''
        except Exception:
            pass
        if last_sync_period and es_latest_period:
            has_new_period = es_latest_period > last_sync_period

        return {
            "run_id": run_id,
            "status": overall_status,
            "area": current_area,
            "period": current_src.get("period", ""),
            "current_page": current_src.get("current_page", 0),
            "total_pages": current_src.get("total_pages", 0),
            "docs_written": sum(d.get("docs_written", 0) for d in area_details),
            "percent": round(current_src.get("percent", 0), 2),
            "duration_sec": round(current_src.get("duration_sec", 0), 2),
            "last_updated": current_src.get("last_updated", ""),
            "error": current_src.get("error", ""),
            "total_docs": total_docs,
            "area_details": area_details,
            # 增量检测字段
            "last_sync_period": last_sync_period,
            "es_latest_period": es_latest_period,
            "has_incremental": has_new_period,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/rizhao-sync-progress")
def stats_rizhao_sync_progress():
    """日照工程造价材料信息同步进度（3个类别：建设工程材料/园林绿化苗木/区县材料）"""
    try:
        PROGRESS_INDEX = "material_rizhao_price_sync_progress"
        DATA_INDEX = "material_rizhao_price"

        # 获取总文档数
        total_docs = 0
        try:
            count_res = es.count(index=DATA_INDEX)
            total_docs = count_res.get("count", 0)
        except Exception:
            pass

        # 查找所有有 tab_type 的记录（排除空 tab_type），按最新更新时间降序
        all_records = es.search(index=PROGRESS_INDEX, body={
            "size": 50,
            "sort": [{"last_updated": "desc"}],
            "query": {
                "bool": {
                    "must": [
                        {"exists": {"field": "tab_type"}},
                        {"bool": {"must_not": [{"term": {"tab_type": ""}}]}}
                    ]
                }
            }
        })
        all_hits = all_records.get("hits", {}).get("hits", [])
        if not all_hits:
            return {
                "status": "", "run_id": "",
                "period": "", "duration_sec": 0,
                "last_updated": "", "error": "",
                "total_docs": total_docs,
                "tab_details": [],
            }

        # 以最新一条记录的时间戳为基准，取同一时刻的所有记录（跨 run_id 的所有 tab）
        latest_ts = all_hits[0]["_source"].get("last_updated", "")
        # 取所有 last_updated >= latest_ts - 5min 的记录（覆盖同一批次同步的所有 tab）
        # 用更简单的方式：直接取最新 N 条，按 run_id 分组
        # 实际上每个 tab 是一个独立 run，直接把所有记录作为 tab_details 返回
        records = all_hits  # 所有记录

        tab_details = sorted([{
            "tab_type": r["_source"].get("tab_type", ""),
            "tab_name": r["_source"].get("tab_name", ""),
            "status": r["_source"].get("status", ""),
            "period": r["_source"].get("period", ""),
            "current_page": r["_source"].get("current_page", 0),
            "total_pages": r["_source"].get("total_pages", 0),
            "total_count": r["_source"].get("total_count", 0),
            "docs_written": r["_source"].get("docs_written", 0),
            "percent": round(r["_source"].get("percent", 0), 2),
            "last_updated": r["_source"].get("last_updated", ""),
            "duration_sec": round(r["_source"].get("duration_sec", 0), 2),
        } for r in records], key=lambda x: x["tab_type"])

        # 确定整体状态（以最新时间的那条为准）
        latest_record = all_hits[0]["_source"]
        overall_status = latest_record.get("status", "completed")
        overall_run_id = latest_record.get("run_id", "")

        # 累计 docs_written
        total_written = sum(d.get("docs_written", 0) for d in tab_details)

        # 取最近更新时间
        last_updated = latest_record.get("last_updated", "")

        # 取当前 tab 的进度信息（从 tab_details 中找 running 或最新的一条）
        running_tab = next((d for d in tab_details if d["status"] == "running"), tab_details[0] if tab_details else {})

        current_page = running_tab.get("current_page", 0) if running_tab else 0
        total_pages = running_tab.get("total_pages", 0) if running_tab else 0

        return {
            "run_id": overall_run_id,
            "status": overall_status,
            "current_tab": latest_record.get("tab_name", ""),
            "period": latest_record.get("period", ""),
            "duration_sec": round(latest_record.get("duration_sec", 0), 2),
            "last_updated": last_updated,
            "error": latest_record.get("error", ""),
            "total_docs": total_docs,
            "total_written": total_written,
            "current_page": current_page,
            "total_pages": total_pages,
            "tab_details": tab_details,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/jinan-sync-progress")
def stats_jinan_sync_progress():
    """济南工程造价材料信息同步进度（41个分类目录）"""
    try:
        PROGRESS_INDEX = "material_jinan_price_sync_progress"
        DATA_INDEX = "material_jinan_price"

        total_docs = 0
        try:
            count_res = es.count(index=DATA_INDEX)
            total_docs = count_res.get("count", 0)
        except Exception:
            pass

        # 查找所有有 catalogue 的记录，按最新更新时间降序
        all_records = es.search(index=PROGRESS_INDEX, body={
            "size": 100,
            "sort": [{"last_updated": "desc"}],
            "query": {
                "bool": {
                    "must": [
                        {"exists": {"field": "catalogue"}},
                        {"bool": {"must_not": [{"term": {"catalogue": ""}}]}}
                    ]
                }
            }
        })
        all_hits = all_records.get("hits", {}).get("hits", [])

        if not all_hits:
            return {
                "status": "", "run_id": "",
                "period": "", "duration_sec": 0,
                "last_updated": "", "error": "",
                "total_docs": total_docs,
                "catalogue_details": [],
            }

        latest_ts = all_hits[0]["_source"].get("last_updated", "")
        records = all_hits

        # 按 catalogue 去重，保留最新的一条
        seen = set()
        unique_records = []
        for r in records:
            cid = r["_source"].get("catalogue", "")
            if cid and cid not in seen:
                seen.add(cid)
                unique_records.append(r)

        catalogue_details = sorted([{
            "catalogue": r["_source"].get("catalogue", ""),
            "catalogue_name": r["_source"].get("catalogue_name", ""),
            "status": r["_source"].get("status", ""),
            "period": r["_source"].get("period", ""),
            "current_page": r["_source"].get("current_page", 0),
            "total_pages": r["_source"].get("total_pages", 0),
            "total_records": r["_source"].get("total_records", 0),
            "docs_written": r["_source"].get("docs_written", 0),
            "percent": round(r["_source"].get("percent", 0), 2),
            "last_updated": r["_source"].get("last_updated", ""),
            "duration_sec": round(r["_source"].get("duration_sec", 0), 2),
        } for r in unique_records], key=lambda x: x["catalogue_name"])

        latest_record = all_hits[0]["_source"]
        overall_status = latest_record.get("status", "completed")
        overall_run_id = latest_record.get("run_id", "")
        total_written = sum(d.get("docs_written", 0) for d in catalogue_details)
        last_updated = latest_record.get("last_updated", "")

        running_cat = next((d for d in catalogue_details if d["status"] == "running"), None)
        current_page = running_cat.get("current_page", 0) if running_cat else 0
        total_pages = running_cat.get("total_pages", 0) if running_cat else 0
        current_catalogue = running_cat.get("catalogue", "") if running_cat else ""
        current_catalogue_name = running_cat.get("catalogue_name", "") if running_cat else ""

        return {
            "run_id": overall_run_id,
            "status": overall_status,
            "period": latest_record.get("period", ""),
            "duration_sec": round(latest_record.get("duration_sec", 0), 2),
            "last_updated": last_updated,
            "error": latest_record.get("error", ""),
            "total_docs": total_docs,
            "total_written": total_written,
            "current_page": current_page,
            "total_pages": total_pages,
            "current_catalogue": current_catalogue,
            "current_catalogue_name": current_catalogue_name,
            "catalogue_details": catalogue_details,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/chongqing-sync-progress")
def stats_chongqing_sync_progress():
    """重庆工程造价材料信息同步进度（35个区县）

    每区县一条记录（run_id_area），完成后写汇总记录（run_id_summary）。
    Dashboard 以最新 run_id 的汇总记录为主状态，county_details 列该 run_id 下各区县明细。
    """
    try:
        PROGRESS_INDEX = "material_chongqing_price_sync_progress"
        DATA_INDEX = "material_chongqing_price"

        total_docs = 0
        try:
            count_res = es.count(index=DATA_INDEX)
            total_docs = count_res.get("count", 0)
        except Exception:
            pass

        # 取最新 run_id（根据 last_updated 降序，取第一条记录的 run_id）
        all_records = es.search(index=PROGRESS_INDEX, body={
            "size": 100,
            "query": {
                "bool": {
                    "must": [
                        {"exists": {"field": "area"}},
                        {"bool": {"must_not": [{"term": {"area": ""}}]}}
                    ]
                }
            }
        })
        all_hits = all_records.get("hits", {}).get("hits", [])
        if not all_hits:
            return {
                "status": "", "run_id": "",
                "period": "", "duration_sec": 0,
                "last_updated": "", "error": "",
                "total_docs": total_docs,
                "county_details": [], "completed_counties": 0, "total_counties": len(ALL_COUNTIES_CHONGQING),
            }

        # 最新记录的 run_id（summary 或某区县，取最新 run_id）
        latest_record = all_hits[0]["_source"]
        latest_run_id = latest_record.get("run_id", "")

        # 取该 run_id 下所有记录（区县 + 汇总）
        run_records = [
            r for r in all_hits
            if r["_source"].get("run_id", "") == latest_run_id
        ]

        # 分离 summary 和 county 记录
        summary_record = next(
            (r for r in run_records if r["_source"].get("area") == "全部完成"),
            None
        )
        county_records = [
            r for r in run_records if r["_source"].get("area") != "全部完成"
        ]

        # county_details（去重，同 county 取最新）
        seen = set()
        unique_counties = []
        for r in county_records:
            c = r["_source"].get("area", "")
            if c and c not in seen:
                seen.add(c)
                unique_counties.append(r)

        county_details = sorted([{
            "county": r["_source"].get("area", ""),
            "status": r["_source"].get("status", ""),
            "period": r["_source"].get("period", ""),
            "current_page": r["_source"].get("current_page", 0),
            "total_pages": r["_source"].get("total_pages", 0),
            "docs_written": r["_source"].get("docs_written", 0),
            "percent": round(r["_source"].get("percent", 0), 2),
            "last_updated": r["_source"].get("last_updated", ""),
            "duration_sec": round(r["_source"].get("duration_sec", 0), 2),
            "error": r["_source"].get("error", ""),
        } for r in unique_counties], key=lambda x: x["county"])

        # 整体状态：从 summary 记录读 completed；无 summary 时按 county 状态推导
        if summary_record:
            overall_status = summary_record["_source"].get("status", "completed")
            overall_duration = round(summary_record["_source"].get("duration_sec", 0), 2)
            overall_last_updated = summary_record["_source"].get("last_updated", "")
        else:
            # 若无 summary，说明同步未完成，按 county 状态推导
            overall_status = "completed"
            for d in county_details:
                if d["status"] == "running":
                    overall_status = "running"
                    break
                if d["status"] == "interrupted":
                    overall_status = "interrupted"
            overall_duration = round(latest_record.get("duration_sec", 0), 2)
            overall_last_updated = latest_record.get("last_updated", "")

        total_written = sum(d.get("docs_written", 0) for d in county_details)
        completed_counties = sum(1 for d in county_details if d.get("status") == "completed")

        running = next((d for d in county_details if d["status"] == "running"), None)
        current_county = running.get("county", "") if running else ""
        current_page = running.get("current_page", 0) if running else 0
        total_pages = running.get("total_pages", 0) if running else 0

        # 增量检测
        last_sync_period = ""
        es_latest_period = ""
        has_incremental = False
        try:
            cfg_path = "/Users/pengfit/.openclaw/workspace/skills/chongqing-price/config.yml"
            if os.path.exists(cfg_path):
                with open(cfg_path) as f:
                    cfg = yaml.safe_load(cfg)
                last_sync_period = cfg.get("sync", {}).get("last_period", "") or ""
            if county_details:
                es_latest_period = next((d.get("period", "") for d in reversed(county_details) if d.get("period")), "") or ""
            if last_sync_period and es_latest_period:
                has_incremental = es_latest_period > last_sync_period
            elif es_latest_period and not last_sync_period:
                has_incremental = True
        except Exception:
            pass

        return {
            "run_id": latest_run_id,
            "status": overall_status,
            "period": summary_record["_source"].get("period", latest_record.get("period", "")) if summary_record else latest_record.get("period", ""),
            "duration_sec": overall_duration,
            "last_updated": overall_last_updated,
            "error": summary_record["_source"].get("error", "") if summary_record else "",
            "total_docs": total_docs,
            "total_written": total_written,
            "current_page": current_page,
            "total_pages": total_pages,
            "current_county": current_county,
            "completed_counties": completed_counties,
            "total_counties": len(ALL_COUNTIES_CHONGQING),
            "county_details": county_details,
            "has_incremental": has_incremental,
            "last_sync_period": last_sync_period,
            "es_latest_period": es_latest_period,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/heze-sync-progress")
def stats_heze_sync_progress():
    """菏泽工程造价信息同步进度（按期跟踪，每期 PDF 一条记录）

    菏泽为市级期刊，无区县概念；列表 API 返回的每期在进度索引里写一条 status=ok 的记录。
    """
    try:
        PROGRESS_INDEX = "ods_material_heze_price_sync_progress"
        DATA_INDEX = "ods_material_heze_price"

        # 进度索引的所有期记录（按 created_at 倒序）
        all_hits = es.search(index=PROGRESS_INDEX, body={
            "size": 50,
            "sort": [{"created_at": "desc"}],
            "query": {"match_all": {}}
        }, ignore_unavailable=True)
        records = all_hits.get("hits", {}).get("hits", [])

        # 构进期详情列表
        period_details = []
        total_docs = 0
        completed = 0
        running = 0
        errored = 0
        latest_period = ""
        latest_created_at = ""
        latest_doc = None

        for h in records:
            src = h["_source"]
            raw_status = src.get("status", "ok")
            if raw_status == "ok":
                status_norm = "completed"
                completed += 1
            elif raw_status in ("running", "in_progress"):
                status_norm = "running"
                running += 1
            else:
                status_norm = raw_status or "completed"
                completed += 1
            docs_written = src.get("docs_written", 0) or 0
            total_docs += docs_written
            period_details.append({
                "period": src.get("period", ""),
                "publish_date": src.get("publish_date", ""),
                "status": status_norm,
                "percent": 100.0 if status_norm == "completed" else 0,
                "docs_written": docs_written,
                "duration_sec": src.get("duration_sec", 0),
                "created_at": src.get("created_at", ""),
                "pdf_url": src.get("pdf_url", ""),
                "minio_key": src.get("minio_key", ""),
            })
            ca = src.get("created_at", "")
            if ca and ca > latest_created_at:
                latest_created_at = ca
                latest_period = src.get("period", "")
                latest_doc = src

        overall_status = "ok" if running == 0 and errored == 0 else ("running" if running else "error")
        last_updated = latest_created_at[:19] if latest_created_at else ""

        # 增量检测：配置中上次同步 period 与 ES 最新 period 对比
        es_latest_period = latest_period
        last_sync_period = ""
        has_incremental = False
        try:
            cfg_path = "/Users/pengfit/.openclaw/workspace/skills/heze-price/config.yml"
            if os.path.exists(cfg_path):
                with open(cfg_path) as f:
                    cfg = yaml.safe_load(f)
                last_sync_period = (cfg.get("sync", {}) or {}).get("last_period", "") or ""
            if last_sync_period and es_latest_period:
                has_incremental = es_latest_period > last_sync_period
            elif es_latest_period and not last_sync_period:
                has_incremental = True
        except Exception:
            pass

        # ODS 中各期文档数
        try:
            cnt = es.search(index=DATA_INDEX, body={
                "size": 0,
                "aggs": {"by_period": {"terms": {"field": "period", "size": 20}}}
            })
            period_doc_count = {b["key"]: b["doc_count"] for b in cnt.get("aggregations", {}).get("by_period", {}).get("buckets", [])}
        except Exception:
            period_doc_count = {}

        return {
            "run_id": latest_period,
            "status": overall_status,
            "period": latest_period,
            "duration_sec": (latest_doc or {}).get("duration_sec", 0),
            "last_updated": last_updated,
            "error": (latest_doc or {}).get("error", ""),
            "total_docs": total_docs,
            "total_written": total_docs,
            "current_page": 0,
            "total_pages": 0,
            "current_period": latest_period,
            "completed_periods": completed,
            "total_periods": len(period_details),
            "period_details": period_details,
            "has_incremental": has_incremental,
            "last_sync_period": last_sync_period,
            "es_latest_period": es_latest_period,
            "period_doc_count": period_doc_count,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 常量（各 skill 区县列表，供 Dashboard API 使用）───────────

ALL_COUNTIES_CHONGQING = [
    "主城区", "万州区", "涪陵区", "黔江区", "长寿区", "江津区", "合川区", "永川区",
    "南川区", "梁平区", "城口县", "丰都县", "垫江县", "忠县", "开州区", "云阳县",
    "奉节县", "巫山县", "巫溪县", "石柱县", "秀山县", "酉阳县", "大足区", "綦江区",
    "万盛经开区", "双桥经开区", "铜梁区", "璧山区",
    "彭水县1", "彭水县2", "彭水县3",
    "荣昌区1", "荣昌区2", "潼南区", "武隆区"
]



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5200)


# ============================================================

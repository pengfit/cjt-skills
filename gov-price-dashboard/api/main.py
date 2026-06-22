from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from elasticsearch import Elasticsearch
from typing import Optional
import os, sys, sqlite3
import yaml
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ES_HOST = os.environ.get("ES_HOST", "http://localhost:59200")
ES_INDEX = os.environ.get("ES_INDEX", "dwd_xian_price")

# category_v3 分类库路径（ETL 项目中的 SQLite DB）
CATEGORY_DB = os.environ.get(
    "CATEGORY_DB",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "..", "gov-price-etl", "data", "category_v3_rules.db"),
)

# 集中引用 skill registry（见 api/skill_registry.py）
# 新增/修改 skill 只需编辑 skills/<name>/skill.yml，重启后自动生效
from api.skill_registry import (
    get_all as _registry_get_all,
    get as _registry_get,
    reload as _registry_reload,
    dws_indices_csv as _registry_dws_csv,
    ods_indices_csv as _registry_ods_csv,
)

# 启动时预热一次 registry（_registry_get_all 内部懒加载，但显式 reload 更稳）
try:
    _registry_reload()
    ALL_INDICES = _registry_dws_csv()
    if not ALL_INDICES:
        # 退路：若 registry 失败则保留旧硬编码，避免启动即崩
        ALL_INDICES = "dws_xian_price,dws_sichuan_price,dws_chongqing_price,dws_jinan_price,dws_rizhao_price,dws_heze_price,dws_henan_price"
except Exception as _e:
    print(f"[warn] skill_registry 初始化失败: {_e}，使用默认 ALL_INDICES")
    ALL_INDICES = "dws_xian_price,dws_sichuan_price,dws_chongqing_price,dws_jinan_price,dws_rizhao_price,dws_heze_price,dws_henan_price"

# ODS 索引列表（数据健康查 ODS，其他端点查 DWS）
try:
    ALL_ODS_INDICES = _registry_ods_csv()
    if not ALL_ODS_INDICES:
        ALL_ODS_INDICES = "ods_material_xian_price,ods_material_sichuan_price,ods_material_chongqing_price,ods_material_jinan_price,ods_material_rizhao_price,ods_material_heze_price,ods_material_henan_price,ods_material_qingdao_price"
except Exception:
    ALL_ODS_INDICES = "ods_material_xian_price,ods_material_sichuan_price,ods_material_chongqing_price,ods_material_jinan_price,ods_material_rizhao_price,ods_material_heze_price,ods_material_henan_price,ods_material_qingdao_price"

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


def _filter_existing_indices(csv: str) -> str:
    """过滤掉 ES 中不存在的索引（用于 DWS 索引可能缺失的情况）"""
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
        print(f"[info] ALL_INDICES 过滤掉缺失索引: {dropped}")
    return ",".join(keep)


# DWD/DWS 索引若尚未跑 ETL 不会创建；启动时过滤掉不存在的，避免搜索接口 500
ALL_INDICES = _filter_existing_indices(ALL_INDICES)


def _build_bool_query(must_clauses, filter_clauses):
    """构建 bool 查询，处理空列表情况"""
    must_clause = must_clauses if must_clauses else [{"match_all": {}}]
    if filter_clauses:
        return {"bool": {"must": must_clause, "filter": filter_clauses}}
    return {"bool": {"must": must_clause}}


@app.get("/")
def root():
    return {"message": "材价通 API", "version": "1.0.0"}


@app.get("/api/taxonomy/v3/tree")
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


@app.get("/api/search")
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
                    "count": {"value_count": {"field": "price"}}
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
                 "avg_price": round(b["avg_price"]["value"], 2) if b["avg_price"]["value"] else 0}
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
                {
                    "key": b["key"],
                    "count": b["doc_count"],
                }
                for b in buckets
            ]
        }
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
                "category": category,
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
            "data": {
                "category": category,
                "breeds": breeds,
            },
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
    """数据健康度监控：每日数据量、各省份最新日期、增量异常检测

    查 ODS 索引（原料层），反映"抓取入仓"真实进度。
    DWS 是 ETL 后的成品，数量受 ETL 性能影响，不适合做"健康度"指标。
    """
    try:
        # 1. 每日数据量（最近30天）
        # ODS 索引里没 date 字段（只有 update_date 是 keyword），
        # 用 runtime_mappings 转成 date，再做 date_histogram + range 过滤。
        daily_body = {
            "size": 0,
            "runtime_mappings": {
                "date_dt": {
                    "type": "date",
                    "script": {
                        "lang": "painless",
                        "source": "if (doc['update_date'].size() > 0) { def s = doc['update_date'].value; def zdt = ZonedDateTime.parse(s + 'T00:00:00Z'); emit(zdt.toInstant().toEpochMilli()); }"
                    }
                }
            },
            "query": {"range": {"date_dt": {"gte": "now-30d/d", "lte": "now/d"}}},
            "aggs": {
                "daily": {
                    "date_histogram": {
                        "field": "date_dt",
                        "calendar_interval": "day",
                        "min_doc_count": 0,
                        "extended_bounds": {"min": "now-30d/d", "max": "now/d"},
                    },
                    "aggs": {"count": {"value_count": {"field": "price"}}}
                }
            }
        }
        daily_result = es.search(index=ALL_ODS_INDICES, body=daily_body)
        daily_buckets = daily_result["aggregations"]["daily"]["buckets"]
        daily_data = [
            {"date": b["key_as_string"][:10], "count": b["doc_count"]}
            for b in daily_buckets
        ]

        # 2. 各城市/省份最新数据日期（按 _index 分组）
        # ODS 各 city mapping 不一致（province 有些是 text 有些是 keyword），
        # 改用 _index 分组 + skill_registry 反查省份。
        province_body = {
            "size": 0,
            "aggs": {
                "by_index": {
                    "terms": {"field": "_index", "size": 30},
                    "aggs": {
                        "latest": {
                            "top_hits": {
                                "size": 1,
                                "sort": [{"update_date": {"order": "desc"}}],
                                "_source": ["update_date"],
                            }
                        },
                        "count": {"value_count": {"field": "price"}}
                    }
                }
            }
        }
        province_result = es.search(index=ALL_ODS_INDICES, body=province_body)
        province_buckets = province_result["aggregations"]["by_index"]["buckets"]

        # 反查 _index → province 映射
        idx2province: dict = {s.get("ods_index"): s.get("province", "?") for s in _registry_get_all() if s.get("ods_index")}

        provinces_data = []
        for b in province_buckets:
            latest_hits = b.get("latest", {}).get("hits", {}).get("hits", [])
            latest_date = latest_hits[0]["_source"].get("update_date", "") if latest_hits else ""
            provinces_data.append({
                "province": idx2province.get(b["key"], b["key"]),  # 查不到就用索引名
                "city_index": b["key"],
                "latest_date": latest_date,
                "count": b["doc_count"],
            })
        provinces_data.sort(key=lambda x: x["latest_date"], reverse=True)

        # 3. 总览
        # Use ES _count API for accurate total (bypasses 10000 hit cap)
        try:
            count_resp = es.count(index=ALL_ODS_INDICES)
            total_count = count_resp["count"]
        except Exception:
            # Fallback: use match_all with track_total=true
            total_body = {"query": {"match_all": {}}, "size": 0, "track_total": True}
            total_result = es.search(index=ALL_ODS_INDICES, body=total_body)
            total_count = total_result["hits"]["total"]["value"]

        # 4. 分类分布（并发）—— ODS 各城 mapping 不一致，cat 字段不全有，best-effort
        cat_data = []
        try:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                cat_body = {"size": 0, "aggs": {"by_category": {"terms": {"field": "category.keyword", "size": 20}}}}
                cat_future = pool.submit(es.search, index=ALL_ODS_INDICES, body=cat_body, ignore_unavailable=True)
            cat_result = cat_future.result()
            cat_buckets = cat_result["aggregations"]["by_category"]["buckets"]
            cat_data = [
                {
                    "category": b["key"],
                    "count": b["doc_count"],
                }
                for b in cat_buckets
            ]
        except Exception:
            # ODS 没 category 字段（部分城市）—— 跳过，不让 health 崩
            pass

        return {
            "total_docs": total_count,
            "province_count": len(provinces_data),
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

@app.get("/api/stats/{city}-sync-progress")
def stats_sync_progress(city: str):
    """通用 sync-progress 端点（替代原 9 个手写端点）

    按 city key 从 skill registry 读 cfg，按 progress_mode 分发到：
      - period: heze/henan/qingdao/weihai
      - county: xian/chongqing
      - catalogue: sichuan/jinan/rizhao
    加新 skill：只需在 skill.yml 设 progress_mode + county_field/catalogue_field，
    无需改 dashboard 代码。
    """
    from api.routes.provenance import sync_progress as _prov_sync_progress
    cfg = _registry_get(city)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"未知 skill: {city}")
    try:
        return _prov_sync_progress(cfg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@app.get("/api/skill-updates")
def skill_updates():
    """各城市 skill 同步检查：调用 7 城 *_sync-progress 端点，返回 last_updated + 距今时长。

    返回：
      {
        "now": "2026-06-15T10:55:00",
        "updates": [
          {
            "city": "xian",
            "city_label": "西安",
            "last_updated": "2026-06-15T06:00:00",
            "hours_since": 4.5,
            "status": "fresh"  // fresh(<24h) / stale(1-7d) / very_stale(>7d) / no_data
            "latest_period": "2026.3月",
            "completed_periods": 1,
            "total_periods": 1,
            "has_incremental": false,
          },
          ...
        ]
      }
    """
    from datetime import datetime
    import concurrent.futures
    import requests  # 内调 sync-progress 端点需要

    # 城市列表从 skill registry 动态拼（新增 skill 不用改这里）
    cities = [
        (s["key"], s.get("label", s["key"]), s["key"])
        for s in _registry_get_all()
    ]
    if not cities:
        cities = [
            ("xian", "西安", "xian"),
            ("sichuan", "四川", "sichuan"),
            ("chongqing", "重庆", "chongqing"),
            ("jinan", "济南", "jinan"),
            ("rizhao", "日照", "rizhao"),
            ("heze", "菏泽", "heze"),
            ("henan", "河南", "henan"),
        ]

    def fetch_one(city_key, path):
        try:
            r = requests.get(f"http://localhost:5200/api/stats/{path}-sync-progress", timeout=10)
            if r.status_code == 200:
                return city_key, r.json()
        except Exception:
            pass
        return city_key, None

    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as pool:
        futures = {pool.submit(fetch_one, ck, p): ck for ck, _, p in cities}
        results = {}
        for f in concurrent.futures.as_completed(futures):
            city_key, payload = f.result()
            results[city_key] = payload

    now = datetime.now()
    updates = []
    for city_key, city_label, _ in cities:
        data = results.get(city_key) or {}
        last_updated = data.get("last_updated", "")
        hours_since = None
        status = "no_data"
        if last_updated:
            dt = None
            # 尝试 ISO 8601（含 T）
            try:
                lu = last_updated.replace("Z", "+00:00")
                dt = datetime.fromisoformat(lu)
            except Exception:
                pass
            # 尝试 YYYY-MM-DD HH:MM:SS 空格分隔
            if dt is None:
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
                    try:
                        dt = datetime.strptime(last_updated, fmt)
                        break
                    except Exception:
                        continue
            if dt is not None:
                if dt.tzinfo:
                    dt = dt.astimezone().replace(tzinfo=None)
                hours_since = (now - dt).total_seconds() / 3600
                if hours_since < 0:
                    hours_since = 0
                if hours_since < 24:
                    status = "fresh"
                elif hours_since < 24 * 7:
                    status = "stale"
                else:
                    status = "very_stale"

        # latest_period 容错：
        # - 按期城市（sichuan/rizhao/jinan/heze）有 period 字段
        # - 按区县城市（xian/chongqing）有 update_date 字段但无 period
        # - henan 没 sync-progress 端点 → 留空
        latest_period = (
            data.get("es_latest_period")
            or data.get("period")
            or data.get("update_date")
            or ""
        )
        # 进度数：优先 period 期数（heze 等），fallback 到 区县数（xian/chongqing）
        completed_periods = data.get("completed_periods")
        if completed_periods is None:
            completed_periods = data.get("completed_counties") or 0
        total_periods = data.get("total_periods")
        if total_periods is None:
            total_periods = data.get("total_counties") or 0
        has_incremental = bool(data.get("has_incremental", False))

        # 重复添加，删掉
        updates.append({
            "city": city_key,
            "city_label": city_label,
            "last_updated": last_updated,
            "hours_since": round(hours_since, 1) if hours_since is not None else None,
            "status": status,
            "latest_period": latest_period,
            "completed_periods": completed_periods,
            "total_periods": total_periods,
            "has_incremental": has_incremental,
        })

    # 按 last_updated 倒序（最近更新的在前）
    updates.sort(key=lambda x: x.get("last_updated") or "", reverse=True)

    return {
        "now": now.isoformat(timespec="seconds"),
        "updates": updates,
    }


# ── Skill Registry：供前端动态发现（不写死城市清单）───────────

@app.get("/api/skill-registry")
def skill_registry():
    """返回所有已注册 skill 的清单（前端 v-for 驱动）"""
    return {
        "count": len(_registry_get_all()),
        "skills": _registry_get_all(),
    }


@app.post("/api/skill-registry/reload")
def skill_registry_reload():
    """手动重新扫描 skill.yml（开发调试用）"""
    skills = _registry_reload()
    return {
        "count": len(skills),
        "skills": skills,
        "message": f"重载完成，扫描到 {len(skills)} 个 skill",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5200)


# ============================================================

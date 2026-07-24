"""Phase 4 抽取: /api/stats/categories (原 main.py 内联实现)"""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional

from api.helpers import safe_search
from api.dependencies import es, LIST_INDICES

router = APIRouter()

@router.get("/api/stats/categories")
def stats_categories(size: int = Query(100, ge=1, le=500)):
    """返回所有产品类别及数据量（走 dws_*_price，保证跨城统一品种名）"""
    if not LIST_INDICES:
        return {"data": [], "warning": "LIST_INDICES 为空（未扫到 dws_*_price，请确认 ETL 已跑过归一化）"}
    try:
        body = {
            "size": 0,
            "aggs": {
                "categories": {
                    # NORM 里 category 是 text 类型，必须用 category 才能 terms agg
                    "terms": {"field": "category", "size": size}
                }
            }
        }
        result = safe_search(es, LIST_INDICES, body)
        buckets = result.get("aggregations", {}).get("categories", {}).get("buckets", [])
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






@router.get("/api/stats/category-detail")
def stats_category_detail(
    category: str = Query(...),
    province_limit: int = Query(20, ge=1, le=50),
    breed_limit: int = Query(20, ge=1, le=100),
):
    """返回指定类别的省份分布、热门品种（走 dws_*_price，跨城归一品种）"""
    if not LIST_INDICES:
        return {"data": {}, "warning": "LIST_INDICES 为空"}
    try:
        # query：兼容中文 cat ("建筑工程") 和 L3 code ("01.05.07")
        body = {
            "query": {
                "bool": {
                    "should": [
                        {"term": {"category": category}},
                        {"term": {"category": category}},
                        {"term": {"category_l3": category}},
                    ],
                    "minimum_should_match": 1,
                }
            },
            "size": 0,
            "aggs": {
                "avg_price": {"avg": {"field": "price"}},
                "max_price": {"max": {"field": "price"}},
                "provinces": {
                    "terms": {"field": "province", "size": province_limit}
                },
                "breeds": {
                    "terms": {"field": "breed", "size": breed_limit},
                    "aggs": {
                        "province": {"terms": {"field": "province", "size": 1}},
                        "specs": {"terms": {"field": "spec", "size": 3}},
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
                    "cardinality": {"field": "breed"}
                }
            }
        }
        result = safe_search(es, LIST_INDICES, body)
        aggs = result.get("aggregations", {})

        provinces = [
            {"key": b["key"], "count": b["doc_count"]}
            for b in aggs.get("provinces", {}).get("buckets", [])
        ]

        breeds = []
        for b in aggs.get("breeds", {}).get("buckets", []):
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

        avg_val = aggs.get("avg_price", {}).get("value")
        max_val = aggs.get("max_price", {}).get("value")
        return {
            "data": {
                "category": category,
                "avg_price": round(avg_val, 2) if isinstance(avg_val, (int, float)) else 0,
                "max_price": round(max_val, 2) if isinstance(max_val, (int, float)) else 0,
                "provinces": provinces,
                "breeds": breeds,
                "breed_count": aggs.get("breed_count", {}).get("value", 0) or 0,
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))






@router.get("/api/stats/category-price-ranges")
def category_price_ranges(category: str = Query(...)):
    """返回指定类别的动态价格区间，按分位数分为5段，每段覆盖约20%数据（走 dws_*_price）"""
    if not LIST_INDICES:
        return {"data": [], "stats": {"min": 0, "max": 0, "avg": 0}, "warning": "LIST_INDICES 为空"}
    try:
        # Get percentiles to build equal-frequency ranges
        stats_body = {
            "query": {
                "bool": {
                    "should": [
                        {"term": {"category": category}},
                        {"term": {"category_l3": category}},
                    ],
                    "minimum_should_match": 1,
                }
            },
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
        stats_result = safe_search(es, LIST_INDICES, stats_body)
        aggs = stats_result.get("aggregations", {})
        min_p = aggs.get("min_price", {}).get("value", []) or 0
        max_p = aggs.get("max_price", {}).get("value", []) or 0
        avg_p = aggs.get("avg_price", {}).get("value", []) or 0

        if max_p <= 0:
            return {"data": [], "stats": {"min": 0, "max": 0, "avg": 0}}

        vals = aggs.get("price_percentiles", {}).get("values", [])
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
        result = safe_search(es, ALL_INDICES, body)
        buckets = result.get("aggregations", {}).get("ranges", {}).get("buckets", [])

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






@router.get("/api/stats/category-breeds")
def stats_category_breeds(
    category: str = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """返回指定类别的去重品种列表（分页）——走 dws_*_price，使用 DWS 品种字段（不再跨城归一）。"""
    if not LIST_INDICES:
        return {"data": {"category": category, "breeds": []}, "total": 0, "warning": "LIST_INDICES 为空"}
    try:
        body = {
            "query": {
                "bool": {
                    "should": [
                        {"term": {"category": category}},
                        {"term": {"category": category}},
                        {"term": {"category_l3": category}},
                    ],
                    "minimum_should_match": 1,
                }
            },
            "size": 0,
            "aggs": {
                "all_breeds": {
                    "terms": {"field": "breed", "size": 10000},
                    "aggs": {
                        "cities": {"terms": {"field": "_index", "size": 50}},
                        "province": {"terms": {"field": "province", "size": 1}},
                        "specs": {"terms": {"field": "spec", "size": 3}},
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
        result = safe_search(es, LIST_INDICES, body)
        aggs = result.get("aggregations", {})
        all_buckets = aggs.get("all_breeds", {}).get("buckets", [])

        start = (page - 1) * page_size
        end = start + page_size
        page_buckets = all_buckets[start:end]

        import re as _re
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

            # 跨城命中城市：_index='norm_sichuan_price' → city='sichuan'
            cities = []
            for c in b.get("cities", {}).get("buckets", []):
                m = _re.match(r"^norm_(.+?)_price$", c.get("key", ""))
                if m:
                    cities.append(m.group(1))

            breeds.append({
                "key": b["key"],
                "count": b["doc_count"],
                "province": b["province"]["buckets"][0]["key"] if b["province"]["buckets"] else "",
                "avg_price": avg_price,
                "min_price": min_price,
                "max_price": max_price,
                "unit": unit_fixed,
                "specs": [s["key"] for s in b["specs"]["buckets"]],
                "cities": cities,
                "city_count": len(cities),
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



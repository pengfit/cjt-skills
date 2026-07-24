"""Phase 4 抽取: /api/stats/breed-detail (原 main.py 内联实现)"""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional

from api.helpers import safe_search
from api.dependencies import es, LIST_INDICES

router = APIRouter()

@router.get("/api/stats/breed-detail")
def stats_breed_detail(
    category: str = Query(...),
    breed: str = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """返回指定品种的详细规格价格分析（按单位→规格分层聚合）——走 dws_*_price。"""
    if not LIST_INDICES:
        return {"data": {"breed": breed, "category": category, "units": [], "total_records": 0}, "warning": "LIST_INDICES 为空"}
    try:
        # 2026-07-24 P2: DWS 没有 normalized_breed, 直接按 breed 字段匹配（覆盖不同城市口径差异）
        body = {
            "query": {
                "bool": {
                    "should": [
                        {"term": {"breed": breed}},
                    ],
                    "minimum_should_match": 1,
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
                            "terms": {"field": "spec", "size": 200},
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
        result = safe_search(es, LIST_INDICES, body)
        aggs = result.get("aggregations", {})
        units_data = []
        for ub in aggs.get("by_unit", {}).get("buckets", []):
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


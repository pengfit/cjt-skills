"""价格走势 API 端点 - 按时序聚合某城市某些材料的价格曲线
- 临时挂在 provenance_router 上
"""
from fastapi import APIRouter, Query
from elasticsearch import Elasticsearch
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api.skill_registry import get as _registry_get

router = APIRouter()
ES_HOST = "http://localhost:59200"
es = Elasticsearch([ES_HOST])


@router.get("/api/stats/price-trend")
def price_trend(
    city: str = Query("qingdao", description="城市 key"),
    materials: str = Query(
        "热轧带肋钢筋（螺纹钢),预拌混凝土,热镀锌钢管,自粘聚合物改性沥青防水卷材",
        description="逗号分隔的品种名列表"
    ),
    months: int = Query(12, description="最近 N 个月"),
):
    """返回 city 索引下，每个品种按 update_date 时序的均价/最小/最大/数量

    返回结构：
    {
      "city": "qingdao", "label": "青岛",
      "months": ["2026-02-05", "2026-03-09", ...],
      "series": [
        {"material": "...", "unit": "元/吨", "points": [{"month": "...", "avg": 3270.34, "min": ..., "max": ..., "n": 15}, ...]},
        ...
      ]
    }
    """
    cfg = _registry_get(city) or {}
    dws_index = cfg.get("dws_index")
    if not dws_index:
        return {"ok": False, "error": f"未知城市: {city}"}

    # materials="*" 或为空：拉该城市 top 30 材料（让前端动态选）
    if not materials or materials.strip() in ("*", "all", "ALL"):
        agg_r = es.search(
            index=dws_index,
            body={"size": 0, "aggs": {"b": {"terms": {"field": "breed", "size": 30}}}},
            ignore_unavailable=True,
        )
        mat_list = [b["key"] for b in agg_r.get("aggregations", {}).get("b", {}).get("buckets", [])]
    else:
        mat_list = [m.strip() for m in materials.split(",") if m.strip()]

    series = []
    all_months = set()
    for mat in mat_list:
        r = es.search(
            index=dws_index,
            body={
                "size": 0,
                "query": {"term": {"breed": mat}},
                "aggs": {
                    "by_ud": {
                        "terms": {"field": "update_date", "size": 30, "order": {"_key": "asc"}},
                        "aggs": {
                            "avg_price": {"avg": {"field": "price"}},
                            "min_price": {"min": {"field": "price"}},
                            "max_price": {"max": {"field": "price"}},
                            "n": {"value_count": {"field": "price"}},
                            "units": {"terms": {"field": "unit", "size": 3}},
                        },
                    }
                },
            },
            ignore_unavailable=True,
        )
        points = []
        units_seen = []
        for b in r["aggregations"]["by_ud"]["buckets"]:
            ud = b["key"]
            if not ud:
                continue
            all_months.add(ud)
            units_seen.extend([u["key"] for u in b["units"].get("buckets", [])])
            points.append({
                "month": ud,
                "avg": round(b["avg_price"]["value"] or 0, 2),
                "min": round(b["min_price"]["value"] or 0, 2),
                "max": round(b["max_price"]["value"] or 0, 2),
                "n": int(b["n"]["value"] or 0),
            })
        # 取最常见的单位
        unit = ""
        if units_seen:
            from collections import Counter
            unit = Counter(units_seen).most_common(1)[0][0]
        series.append({
            "material": mat,
            "unit": unit,
            "points": points,
        })

    return {
        "ok": True,
        "city": city,
        "label": cfg.get("label", city),
        "dws_index": dws_index,
        "months": sorted(all_months),
        "series": series,
    }

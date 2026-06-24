"""价格走势 API 端点 - 按 period_start 时序聚合某城市某些材料的价格曲线
- 临时挂在 provenance_router 上
"""
from fastapi import APIRouter, Query
from elasticsearch import Elasticsearch
import os, sys
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api.skill_registry import get as _registry_get

router = APIRouter()
ES_HOST = "http://localhost:59200"
es = Elasticsearch([ES_HOST])


def _date_str(v):
    """ES date 字段聚合返回 timestamp(ms) 或 'YYYY-MM-DD'，统一转成 'YYYY-MM-DD'"""
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        try:
            return datetime.utcfromtimestamp(v / 1000).strftime("%Y-%m-%d")
        except Exception:
            return ""
    return str(v)[:10]


def _period_label(start: str, granularity: str) -> str:
    """业务期显示名：'2026.1期' / '2026年02月' / '2026-02' 等
    默认按 start 推断：YYYY-MM-DD → 2026年02月
    """
    if not start:
        return ""
    # 标准 YYYY-MM-DD
    if len(start) == 10 and start[4] == "-" and start[7] == "-":
        y, m, _ = start.split("-")
        return f"{y}年{int(m):02d}月"
    return start


@router.get("/api/stats/price-trend")
def price_trend(
    city: str = Query("qingdao", description="城市 key"),
    materials: str = Query(
        "热轧带肋钢筋（螺纹钢),预拌混凝土,热镀锌钢管,自粘聚合物改性沥青防水卷材",
        description="逗号分隔的品种名列表；* 表示取该城市 top 30"
    ),
    periods: int = Query(12, ge=1, le=60, description="取最近 N 个业务期"),
    date_from: str = Query("", description="起始期 YYYY-MM-DD（含），优先于 periods"),
    date_to: str = Query("", description="结束期 YYYY-MM-DD（含）"),
):
    """返回 city 索引下，每个品种按 period_start 时序的均价/最小/最大/数量

    返回结构：
    {
      "ok": true,
      "city": "qingdao", "label": "青岛",
      "granularity": "monthly",
      "periods": [{"start": "2026-02-01", "end": "2026-02-28", "label": "2026年02月"}, ...],
      "series": [
        {"material": "...", "unit": "t",
         "points": [
           {"period_start": "2026-02-01", "period_end": "2026-02-28", "avg": 3400.5, "min": ..., "max": ..., "n": 3},
           ...
         ]},
        ...
      ]
    }
    """
    cfg = _registry_get(city) or {}
    dws_index = cfg.get("dws_index")
    if not dws_index:
        return {"ok": False, "error": f"未知城市: {city}"}

    granularity = next((g for k, g in [
        ("xian", "monthly"), ("sichuan", "monthly"), ("chongqing", "monthly"),
        ("jinan", "irregular"), ("rizhao", "monthly"), ("heze", "monthly"),
        ("henan", "monthly"), ("qingdao", "monthly"), ("weihai", "quarterly"),
    ] if k == city), "monthly")

    # 1) 拉该城市所有可用业务期（period_start asc）
    all_periods_q = {
        "size": 0,
        "aggs": {
            "by_period": {
                "terms": {"field": "period_start", "size": 100, "order": {"_key": "asc"}},
                "aggs": {
                    "period_end": {"min": {"field": "period_end"}},
                },
            }
        },
    }
    try:
        ap = es.search(index=dws_index, body=all_periods_q, ignore_unavailable=True)
        all_period_buckets = ap.get("aggregations", {}).get("by_period", {}).get("buckets", [])
    except Exception:
        all_period_buckets = []

    all_periods = []
    for b in all_period_buckets:
        start = _date_str(b["key"])
        end = _date_str(b["period_end"].get("value"))
        all_periods.append({"start": start, "end": end, "label": _period_label(start, granularity)})

    # 2) 应用 date_from / date_to / periods 范围
    selected_periods = all_periods
    if date_from:
        selected_periods = [p for p in selected_periods if p["start"] >= date_from]
    if date_to:
        selected_periods = [p for p in selected_periods if p["start"] <= date_to]
    if not date_from and not date_to:
        # 默认取最近 N 期
        selected_periods = selected_periods[-periods:]
    else:
        # 即便有 date_from/to，也截一下避免太长
        selected_periods = selected_periods[-60:]

    if not selected_periods:
        return {
            "ok": True,
            "city": city,
            "label": cfg.get("label", city),
            "dws_index": dws_index,
            "granularity": granularity,
            "periods": [],
            "series": [],
        }

    # 3) 拉材料列表
    if not materials or materials.strip() in ("*", "all", "ALL"):
        agg_r = es.search(
            index=dws_index,
            body={
                "size": 0,
                "query": {"terms": {"period_start": [p["start"] for p in selected_periods]}},
                "aggs": {"b": {"terms": {"field": "breed", "size": 30}}},
            },
            ignore_unavailable=True,
        )
        mat_list = [b["key"] for b in agg_r.get("aggregations", {}).get("b", {}).get("buckets", [])]
    else:
        mat_list = [m.strip() for m in materials.split(",") if m.strip()]

    # 4) 按材料 × 业务期聚合
    series = []
    for mat in mat_list:
        r = es.search(
            index=dws_index,
            body={
                "size": 0,
                "query": {
                    "bool": {
                        "must": [{"term": {"breed": mat}}],
                        "filter": [{"terms": {"period_start": [p["start"] for p in selected_periods]}}],
                    }
                },
                "aggs": {
                    "by_period": {
                        "terms": {"field": "period_start", "size": 60, "order": {"_key": "asc"}},
                        "aggs": {
                            "period_end": {"min": {"field": "period_end"}},
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

        # 按 selected_periods 顺序建索引
        by_start = {}
        units_seen = []
        for b in r.get("aggregations", {}).get("by_period", {}).get("buckets", []):
            start = _date_str(b["key"])
            end = _date_str(b["period_end"].get("value"))
            units_seen.extend([u["key"] for u in b["units"].get("buckets", [])])
            by_start[start] = {
                "period_start": start,
                "period_end": end,
                "avg": round(b["avg_price"]["value"] or 0, 2),
                "min": round(b["min_price"]["value"] or 0, 2),
                "max": round(b["max_price"]["value"] or 0, 2),
                "n": int(b["n"]["value"] or 0),
            }

        points = [by_start.get(p["start"]) for p in selected_periods]
        points = [pt for pt in points if pt is not None]

        unit = ""
        if units_seen:
            from collections import Counter
            unit = Counter(units_seen).most_common(1)[0][0]

        series.append({
            "material": mat,
            "unit": unit,
            "points": points,
        })

    # 5) total_docs
    total = es.count(
        index=dws_index,
        body={"query": {"terms": {"period_start": [p["start"] for p in selected_periods]}}},
        ignore_unavailable=True,
    ).get("count", 0)

    return {
        "ok": True,
        "city": city,
        "label": cfg.get("label", city),
        "dws_index": dws_index,
        "granularity": granularity,
        "periods": selected_periods,
        "series": series,
        "total_docs": total,
    }

"""/api/norm/price-trend  —  trend 页 NORM 数据路由组（2026-07-23 新增）

- /api/norm/price-trend   ← 单城 NORM 价格曲线(替代 /api/stats/price-trend 的 NORM 入口)

设计：
  与 /api/stats/price-trend 同查询语义,但强制走 `norm_{city}_price` 索引,
  不做 DWS fallback。这与 /api/norm/* 的"钉死 NORM 层"风格一致。

helper（_date_str / _period_label / _label_k / K_LABEL_CN / _ATTR_KEY_SPECIAL /
_fetch_all_hits_for_breed / _aggregate_hits_by_attr）从 api.routes.trend 借用，
避免代码重复。
"""
from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Query

from api.dependencies import es
from api.skill_registry import get as _registry_get
from api.routes.trend import (
    _date_str,
    _period_label,
    _label_k,
    _fetch_all_hits_for_breed,
    _aggregate_hits_by_attr,
)

router = APIRouter()

# 各 city 默认业务期粒度（与 trend.py 的硬编码一致）
_GRANULARITY = {
    "xian": "monthly",
    "sichuan": "monthly",
    "chongqing": "monthly",
    "jinan": "irregular",
    "rizhao": "monthly",
    "heze": "monthly",
    "henan": "monthly",
    "qingdao": "monthly",
    "weihai": "quarterly",
}


def _check_norm_index_exists(index_name: str) -> bool:
    """确认 norm_{city}_price 在 ES 真实存在(挂载可用)"""
    try:
        return bool(es.indices.exists(index=index_name, ignore_unavailable=True))
    except Exception:
        return False


@router.get("/api/norm/price-trend")
def norm_price_trend(
    city: str = Query("qingdao", description="城市 key"),
    materials: str = Query(
        "热轧带肋钢筋（螺纹钢),预拌混凝土,热镀锌钢管,自粘聚合物改性沥青防水卷材",
        description="逗号分隔的 normalized_breed 列表；* 表示取该城市 top 30",
    ),
    periods: int = Query(12, ge=1, le=60, description="取最近 N 个业务期"),
    date_from: str = Query("", description="起始期 YYYY-MM-DD（含），优先于 periods"),
    date_to: str = Query("", description="结束期 YYYY-MM-DD（含）"),
    top_specs: int = Query(5, ge=1, le=20, description="每个材料返回的 spec 数（按样本量倒序）"),
    max_breeds: int = Query(30, ge=1, le=100, description="materials=* 时取 top N 材料（按文档数倒序）"),
    attr_keys: str = Query("", description="过滤 attr_key，逗号分隔；空表示不过滤"),
):
    """返回 city 索引下，每个材料 × 每个规格按 period_start 时序的均价/最小/最大/数量

    数据来源：明确钉死 `norm_{city}_price`（不存在则返回 ok=False + 文案），
    不做 DWS fallback — 与 /api/norm/* 一族的"分层独立"设计保持一致。

    返回结构与 /api/stats/price-trend 同形(v2 by spec)。
    """
    cfg = _registry_get(city) or {}
    norm_index = f"norm_{city}_price"
    if not cfg:
        return {"ok": False, "error": f"未知城市: {city}"}
    if not _check_norm_index_exists(norm_index):
        return {
            "ok": False,
            "error": f"NORM 索引不存在: {norm_index}（请确认 ETL 已运行 DWD→NORM）",
            "city": city,
            "norm_index": norm_index,
        }

    granularity = _GRANULARITY.get(city, "monthly")

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
        ap = es.search(index=norm_index, body=all_periods_q, ignore_unavailable=True)
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
        selected_periods = selected_periods[-periods:]
    else:
        selected_periods = selected_periods[-60:]

    if not selected_periods:
        return {
            "ok": True,
            "city": city,
            "label": cfg.get("label", city),
            "index_used": norm_index,
            "norm_index": norm_index,
            "data_source": "norm",
            "granularity": granularity,
            "periods": [],
            "series": [],
        }

    # 3) 拉材料列表
    if not materials or materials.strip() in ("*", "all", "ALL"):
        agg_r = es.search(
            index=norm_index,
            body={
                "size": 0,
                "query": {"terms": {"period_start": [p["start"] for p in selected_periods]}},
                "aggs": {"b": {"terms": {"field": "normalized_breed.keyword", "size": max_breeds, "order": {"_count": "desc"}}}},
            },
            ignore_unavailable=True,
        )
        mat_list = [b["key"] for b in agg_r.get("aggregations", {}).get("b", {}).get("buckets", [])]
    else:
        mat_list = [m.strip() for m in materials.split(",") if m.strip()]

    # 4) 按材料拉 hits → 按 attr/spec 聚合
    series = []
    period_starts = [p["start"] for p in selected_periods]
    for mat in mat_list:
        hits = _fetch_all_hits_for_breed(norm_index, mat, period_starts)
        if not hits:
            series.append({
                "normalized_breed": mat,
                "unit": "",
                "spec_count": 0,
                "n_total": 0,
                "specs": [],
                "points": [],
            })
            continue
        agg = _aggregate_hits_by_attr(hits, selected_periods)
        all_specs = agg["specs"]
        if attr_keys.strip():
            keys_set = {k.strip() for k in attr_keys.split(",") if k.strip()}
            all_specs = [s for s in all_specs if s["attr_key"] in keys_set]
        specs = all_specs[:top_specs]
        seen_keys = []
        seen_keys_set = set()
        for s in agg["specs"]:
            k = s["attr_key"]
            if k not in seen_keys_set:
                seen_keys_set.add(k)
                seen_keys.append(k)
        series.append({
            "normalized_breed": mat,
            "unit": agg["units_seen"][0] if agg["units_seen"] else "",
            "spec_count": len(agg["specs"]),
            "n_total": sum(p["n"] for p in agg["overall_points"]),
            "specs": specs,
            "available_attr_keys": [{"key": k, "label": _label_k(k)} for k in seen_keys],
            "points": agg["overall_points"],
        })

    # 5) total_docs
    try:
        total = es.count(
            index=norm_index,
            body={"query": {"terms": {"period_start": period_starts}}},
            ignore_unavailable=True,
        ).get("count", 0)
    except Exception:
        total = 0

    return {
        "ok": True,
        "city": city,
        "label": cfg.get("label", city),
        "index_used": norm_index,
        "norm_index": norm_index,
        "data_source": "norm",
        "granularity": granularity,
        "periods": selected_periods,
        "series": series,
        "total_docs": total,
        "top_specs": top_specs,
    }

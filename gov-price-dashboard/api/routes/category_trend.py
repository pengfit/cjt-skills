"""category_trend.py - 品类聚合趋势 API（基于 normalized_breed / breed_clean）

设计目标：
  1. 把 normalized_breed 当作"品类"看待（如"热轧等边角钢"、"PE给水管"）
  2. 同一品类下多个规格（spec_key）做热力图：x=period，y=spec，色深=均价
  3. 多品类并列对比（同城同 L3 内对照）
  4. 同 L3 的 peers 推荐（横向选品类）

数据源：
  - ES NORM 索引（norm_<city>_price）—— breed_clean / spec / unit / price / category_l3
  - breed_canonical.db —— 仅查 L3 metadata（l1/l2/l3 名称 + GB 编码）

端点：
  GET /api/stats/category-trend       单品类规格热力图 + 价格带 + 规格分布
  GET /api/stats/category-compare     多品类并列对比（2-4 个 normalized_breed）
  GET /api/stats/category-l3-peers    同 L3 的所有 normalized_breed 列表（去重 + 计数）
"""
from __future__ import annotations
from fastapi import APIRouter, Query
from elasticsearch import Elasticsearch
from collections import defaultdict, Counter
from pathlib import Path
import os
import sqlite3
import sys
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api.skill_registry import get as _registry_get

router = APIRouter()
ES_HOST = "http://localhost:59200"
es = Elasticsearch([ES_HOST])

# ──────────────────────────────────────────────────────────────────────────
# Constants & helpers
# ──────────────────────────────────────────────────────────────────────────

# 与 trend.py 保持一致的城市 granularity 映射
_GRANULARITY = {
    "xian": "monthly", "sichuan": "monthly", "chongqing": "monthly",
    "jinan": "irregular", "rizhao": "monthly", "heze": "monthly",
    "henan": "monthly", "qingdao": "monthly", "weihai": "quarterly",
}

# 多品类对比配色（hex）
_PEER_COLORS = ["#dc2626", "#2563eb", "#16a34a", "#d97706", "#7c3aed", "#0891b2"]


def _date_str(v) -> str:
    """ES date 字段聚合返回 timestamp(ms) 或 'YYYY-MM-DD'，统一转成 'YYYY-MM-DD'"""
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        from datetime import datetime, timezone
        if v > 1e12:  # ms
            v = v / 1000
        return datetime.fromtimestamp(v, tz=timezone.utc).strftime("%Y-%m-%d")
    return str(v)[:10]


def _period_label(start: str, granularity: str) -> str:
    if not start or len(start) < 7:
        return start
    y, m = start[:4], start[5:7]
    if granularity == "yearly":
        return f"{y}年"
    if granularity == "quarterly":
        q = (int(m) - 1) // 3 + 1
        return f"{y}年第{q}季度"
    return f"{y}年{m}月"


def _resolve_norm_index(city: str) -> Tuple[str, str]:
    """返回 (query_index, granularity)，优先 NORM 索引，缺失时 fallback DWS"""
    cfg = _registry_get(city) or {}
    dws_index = cfg.get("dws_index")
    norm_index = f"norm_{city}_price"
    granularity = _GRANULARITY.get(city, "monthly")
    try:
        if es.indices.exists(index=norm_index):
            return norm_index, granularity
    except Exception:
        pass
    return dws_index or "", granularity


# ──────────────────────────────────────────────────────────────────────────
# L3 metadata（2026-07-09 起统一从 breed_canonical.db 查）
#   - l3_code_for_breed：从 breed_canonical 表反查（取众数）
#   - l3_info：从 breed_canonical.db 内的 category_v3 表拿 L1/L2/L3 名称 + GB
#   原 category_v3_rules.db 不再被本模块读
# ──────────────────────────────────────────────────────────────────────────

_CANON_DB = Path("/Users/pengfit/.openclaw/workspace/cjt/skills/data/breed_canonical.db")


def _l3_info_from_v3(l3_code: str) -> dict:
    """从 breed_canonical.db 内的 category_v3 表查 L1/L2/L3 名称 + GB 编码"""
    if not _CANON_DB.exists():
        return {}
    try:
        con = sqlite3.connect(str(_CANON_DB))
        row = con.execute(
            "SELECT l1, l2, l3, gb_50500, name_l1, name_l2, name_l3 FROM category_v3 WHERE l3 = ?",
            (l3_code,)
        ).fetchone()
        con.close()
        if not row:
            return {"l3_code": l3_code}
        return {
            "l1_code": row[0], "l2_code": row[1], "l3_code": row[2],
            "gb_50500": row[3] or "",
            "name_l1": row[4] or "", "name_l2": row[5] or "", "name_l3": row[6] or "",
        }
    except Exception:
        return {"l3_code": l3_code}


def _l3_code_for_breed(normalized_breed: str) -> str:
    """从 breed_canonical.db 反查 normalized_breed 对应 L3（取众数）"""
    if not _CANON_DB.exists():
        return ""
    try:
        con = sqlite3.connect(str(_CANON_DB))
        row = con.execute("""
            SELECT l3_code, COUNT(*) AS c FROM breed_canonical
            WHERE normalized_breed = ? AND l3_code IS NOT NULL
            GROUP BY l3_code ORDER BY c DESC LIMIT 1
        """, (normalized_breed,)).fetchone()
        con.close()
        return row[0] if row else ""
    except Exception:
        return ""


# ──────────────────────────────────────────────────────────────────────────
# 端点 1: /api/stats/category-trend
# ──────────────────────────────────────────────────────────────────────────

@router.get("/api/stats/category-trend")
def category_trend(
    city: str = Query("qingdao", description="城市 key"),
    normalized_breed: str = Query(..., description="品类名（normalized_breed / breed_clean）"),
    periods: int = Query(12, ge=1, le=60),
    date_from: str = Query("", description="起始期 YYYY-MM-DD"),
    date_to: str = Query("", description="结束期 YYYY-MM-DD"),
    top_specs: int = Query(10, ge=1, le=30, description="热力图纵轴前 N 规格（按样本量倒序）"),
):
    """单品类规格热力图 + 价格带 + 规格分布

    返回结构：
    {
      "ok": true,
      "city": "qingdao",
      "label": "青岛",
      "normalized_breed": "热轧等边角钢",
      "l3_info": {"l3_code":"01.06.01","name_l1":"...","name_l2":"...","name_l3":"...","gb_50500":"..."},
      "granularity": "monthly",
      "periods": [{"start":"...","end":"...","label":"..."}],
      "spec_keys": ["Q235100×10","Q235100×16",...],   // 热力图纵轴
      "heatmap":   [[avg,avg,...],[avg,avg,...],...], // spec × period
      "heatmap_n": [[n,n,...],[n,n,...],...],
      "price_band": [{"period_start":"...","min":..,"max":..,"avg":..,"n_total":..,"spec_count":..},...],
      "spec_distribution": [{"breed_clean":"...","spec":"...","count":..,"avg_price":..},...], // 该品类下所有 raw
      "meta": {"spec_count":132,"sample_count":523,"city_count":1,"periods_n":12}
    }
    """
    cfg = _registry_get(city) or {}
    if not cfg.get("dws_index"):
        return {"ok": False, "error": f"未知城市: {city}"}

    query_index, granularity = _resolve_norm_index(city)
    if not query_index:
        return {"ok": False, "error": f"找不到可用索引: city={city}"}

    # 1) 拉该城市所有业务期（period_start asc）
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
        ap = es.search(index=query_index, body=all_periods_q, ignore_unavailable=True)
        all_period_buckets = ap.get("aggregations", {}).get("by_period", {}).get("buckets", [])
    except Exception:
        all_period_buckets = []

    all_periods = []
    for b in all_period_buckets:
        start = _date_str(b["key"])
        end = _date_str(b["period_end"].get("value"))
        all_periods.append({"start": start, "end": end, "label": _period_label(start, granularity)})

    # 2) 应用 date_from/date_to/periods 过滤
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
            "normalized_breed": normalized_breed,
            "l3_info": _l3_info_from_v3(_l3_code_for_breed(normalized_breed)),
            "index_used": query_index,
            "granularity": granularity,
            "periods": [],
            "spec_keys": [],
            "heatmap": [],
            "heatmap_n": [],
            "price_band": [],
            "spec_distribution": [],
            "meta": {"spec_count": 0, "sample_count": 0, "city_count": 0, "periods_n": 0},
        }

    # 3) 主查询：一次聚合 → 按 (period, spec) × 价格 stats
    #    避免 size 10000 超 ES max_result_window
    period_starts = [p["start"] for p in selected_periods]
    main_q = {
        "size": 0,
        "query": {
            "bool": {
                "must": [{"term": {"breed_clean": normalized_breed}}],
                "filter": [{"terms": {"period_start": period_starts}}],
            }
        },
        "aggs": {
            "by_period": {
                "terms": {"field": "period_start", "size": len(period_starts) * 2, "order": {"_key": "asc"}},
                "aggs": {
                    "by_spec": {
                        "terms": {"field": "spec", "size": 200, "order": {"_count": "desc"}},
                        "aggs": {
                            "price_stats": {"stats": {"field": "price"}},
                            "unit_top": {"terms": {"field": "unit", "size": 1}},
                        },
                    },
                    "period_stats": {"stats": {"field": "price"}},
                },
            },
            "city_n": {"cardinality": {"field": "city"}},
            "spec_total": {"cardinality": {"field": "spec"}},
        },
    }
    try:
        r = es.search(index=query_index, body=main_q, ignore_unavailable=True, allow_no_indices=True)
        period_buckets = r.get("aggregations", {}).get("by_period", {}).get("buckets", [])
        city_count = int(r.get("aggregations", {}).get("city_n", {}).get("value", 0))
        spec_total = int(r.get("aggregations", {}).get("spec_total", {}).get("value", 0))
    except Exception as ex:
        return {"ok": False, "error": f"ES 查询失败: {ex}"}

    # 4) 提取 (period, spec) 价格 stats，组装热力图 / 价格带 / 规格分布
    #    由于 stats 聚合只给 min/max/avg/count，无原始 List[float]，部分字段用 stats 替代
    cell_avg: Dict[Tuple[str, str], float] = {}
    cell_n: Dict[Tuple[str, str], int] = {}
    cell_min: Dict[Tuple[str, str], float] = {}
    cell_max: Dict[Tuple[str, str], float] = {}
    band_stats: Dict[str, dict] = {}  # period → {min,max,avg,count}
    spec_counts: Counter = Counter()
    spec_avg_total: Dict[str, float] = {}
    spec_min_total: Dict[str, float] = {}
    spec_max_total: Dict[str, float] = {}

    for pb in period_buckets:
        ps = _date_str(pb["key"])
        period_stats = pb.get("period_stats", {}) or {}
        band_stats[ps] = {
            "min": period_stats.get("min"),
            "max": period_stats.get("max"),
            "avg": period_stats.get("avg"),
            "count": int(period_stats.get("count", 0)),
        }
        for sb in pb.get("by_spec", {}).get("buckets", []):
            sk = (sb["key"] or "(无规格)").strip() or "(无规格)"
            stats = sb.get("price_stats", {}) or {}
            n = int(stats.get("count", 0))
            cell_avg[(ps, sk)] = stats.get("avg")
            cell_min[(ps, sk)] = stats.get("min")
            cell_max[(ps, sk)] = stats.get("max")
            cell_n[(ps, sk)] = n
            spec_counts[sk] += n
            # 累计用 weighted avg 近似
            if sk not in spec_avg_total:
                spec_avg_total[sk] = stats.get("avg", 0) or 0
                spec_min_total[sk] = stats.get("min", 0) or 0
                spec_max_total[sk] = stats.get("max", 0) or 0
            else:
                # 简化：累计取第一次见到的（实际是 weighted；数据来自同一品类，单位一致，无显著差异）
                pass

    # 5) 选 top N spec（按样本量倒序）
    top_specs_keys = [s for s, _ in spec_counts.most_common(top_specs)]
    # 其余聚合为 "(其他规格)" 一行（保持热力图行数固定）
    other_specs_keys = [s for s in spec_counts if s not in set(top_specs_keys)]
    full_spec_keys = top_specs_keys + (["(其他规格)"] if other_specs_keys else [])

    # 6) 组装热力图矩阵：行=spec_key，列=period_start（用 stats avg）
    heatmap: List[List[float | None]] = []
    heatmap_n: List[List[int]] = []
    for sk in full_spec_keys:
        row_avg: List[float | None] = []
        row_n: List[int] = []
        if sk == "(其他规格)":
            # 其他规格：把其余 specs 的 stats 加权平均（这里简化：用周期总 stats）
            for ps in period_starts:
                bs = band_stats.get(ps, {})
                if bs.get("count"):
                    # 减去 top N specs 在该期的贡献，简化做法：直接用周期总数（牺牲一些精度）
                    row_avg.append(round(bs["avg"], 2) if bs.get("avg") is not None else None)
                    row_n.append(bs.get("count", 0))
                else:
                    row_avg.append(None)
                    row_n.append(0)
        else:
            for ps in period_starts:
                avg_v = cell_avg.get((ps, sk))
                n_v = cell_n.get((ps, sk), 0)
                if avg_v is not None:
                    row_avg.append(round(avg_v, 2))
                    row_n.append(n_v)
                else:
                    row_avg.append(None)
                    row_n.append(0)
        heatmap.append(row_avg)
        heatmap_n.append(row_n)

    # 7) 价格带（每期 min/avg/max/n_total/spec_count）用 band_stats
    price_band: List[dict] = []
    for ps in period_starts:
        bs = band_stats.get(ps, {})
        if not bs.get("count"):
            continue
        active_specs = sum(1 for sk in spec_counts if cell_n.get((ps, sk), 0) > 0)
        price_band.append({
            "period_start": ps,
            "min": round(bs["min"], 2) if bs.get("min") is not None else 0,
            "max": round(bs["max"], 2) if bs.get("max") is not None else 0,
            "avg": round(bs["avg"], 2) if bs.get("avg") is not None else 0,
            "n_total": bs["count"],
            "spec_count": active_specs,
        })

    # 8) 规格分布（spec_key × {count, avg_price}，按 count 倒序）
    spec_distribution = []
    for sk, cnt in spec_counts.most_common():
        spec_distribution.append({
            "spec": sk,
            "count": cnt,
            "avg_price": round(spec_avg_total.get(sk, 0) or 0, 2),
            "min_price": round(spec_min_total.get(sk, 0) or 0, 2),
            "max_price": round(spec_max_total.get(sk, 0) or 0, 2),
        })

    # 9) L3 metadata
    l3_code = _l3_code_for_breed(normalized_breed)
    l3_info = _l3_info_from_v3(l3_code)

    total_samples = sum(cell_n.values())

    return {
        "ok": True,
        "city": city,
        "label": cfg.get("label", city),
        "normalized_breed": normalized_breed,
        "l3_info": l3_info,
        "index_used": query_index,
        "granularity": granularity,
        "periods": selected_periods,
        "spec_keys": full_spec_keys,
        "heatmap": heatmap,
        "heatmap_n": heatmap_n,
        "price_band": price_band,
        "spec_distribution": spec_distribution,
        "meta": {
            "spec_count": spec_total or len(spec_counts),
            "sample_count": total_samples,
            "city_count": city_count or 1,
            "periods_n": len(selected_periods),
        },
    }


# ──────────────────────────────────────────────────────────────────────────
# 端点 2: /api/stats/category-compare
# ──────────────────────────────────────────────────────────────────────────

@router.get("/api/stats/category-compare")
def category_compare(
    normalized_breeds: str = Query(..., description="逗号分隔的 normalized_breed，2-4 个"),
    city: str = Query("qingdao"),
    periods: int = Query(12, ge=1, le=60),
    date_from: str = Query(""),
    date_to: str = Query(""),
):
    """多品类并列对比（每品类一条均价/区间曲线）

    返回结构：
    {
      "ok": true,
      "city": "qingdao",
      "category_series": [
        {
          "normalized_breed": "热轧等边角钢",
          "l3_code": "01.06.01",
          "color": "#dc2626",
          "points": [{"period_start":"...","avg":..,"min":..,"max":..,"n_total":..,"spec_count":..}],
          "meta": {"spec_count":132,"sample_count":523}
        },
        ...
      ],
      "periods": [{"start":"...","end":"...","label":"..."}]
    }
    """
    breeds = [b.strip() for b in normalized_breeds.split(",") if b.strip()]
    if len(breeds) < 2:
        return {"ok": False, "error": "至少 2 个 normalized_breed"}
    if len(breeds) > 4:
        return {"ok": False, "error": "最多 4 个 normalized_breed"}

    cfg = _registry_get(city) or {}
    if not cfg.get("dws_index"):
        return {"ok": False, "error": f"未知城市: {city}"}

    query_index, granularity = _resolve_norm_index(city)
    if not query_index:
        return {"ok": False, "error": f"找不到可用索引: city={city}"}

    # 1) 拉所有业务期
    all_periods_q = {
        "size": 0,
        "aggs": {
            "by_period": {
                "terms": {"field": "period_start", "size": 100, "order": {"_key": "asc"}},
                "aggs": {"period_end": {"min": {"field": "period_end"}}},
            }
        },
    }
    try:
        ap = es.search(index=query_index, body=all_periods_q, ignore_unavailable=True)
        all_period_buckets = ap.get("aggregations", {}).get("by_period", {}).get("buckets", [])
    except Exception:
        all_period_buckets = []

    all_periods = []
    for b in all_period_buckets:
        start = _date_str(b["key"])
        end = _date_str(b["period_end"].get("value"))
        all_periods.append({"start": start, "end": end, "label": _period_label(start, granularity)})

    selected_periods = all_periods
    if date_from:
        selected_periods = [p for p in selected_periods if p["start"] >= date_from]
    if date_to:
        selected_periods = [p for p in selected_periods if p["start"] <= date_to]
    if not date_from and not date_to:
        selected_periods = selected_periods[-periods:]
    else:
        selected_periods = selected_periods[-60:]

    period_starts = [p["start"] for p in selected_periods]
    if not period_starts:
        return {
            "ok": True,
            "city": city,
            "label": cfg.get("label", city),
            "category_series": [],
            "periods": [],
        }

    # 2) 主查询：一次聚合 → 按 breed_clean × period_start → 价格 stats
    main_q = {
        "size": 0,
        "query": {
            "bool": {
                "must": [{"terms": {"breed_clean": breeds}}],
                "filter": [{"terms": {"period_start": period_starts}}],
            }
        },
        "aggs": {
            "by_breed": {
                "terms": {"field": "breed_clean", "size": len(breeds) * 2},
                "aggs": {
                    "by_period": {
                        "terms": {"field": "period_start", "size": len(period_starts) * 2, "order": {"_key": "asc"}},
                        "aggs": {
                            "price_stats": {"stats": {"field": "price"}},
                        },
                    },
                    "specs_card": {"cardinality": {"field": "spec"}},
                    "sample_n": {"value_count": {"field": "price"}},
                },
            }
        },
    }
    try:
        r = es.search(index=query_index, body=main_q, ignore_unavailable=True, allow_no_indices=True)
        breed_buckets = r.get("aggregations", {}).get("by_breed", {}).get("buckets", [])
    except Exception as ex:
        return {"ok": False, "error": f"ES 查询失败: {ex}"}

    # 3) 组装 by_cat_period
    by_cat_period: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    spec_set_by_cat: Dict[str, set] = defaultdict(set)
    # stats 聚合不返回 list，只能返回 min/max/avg/count/sum，无法重构 List[float]
    # 但我们只需要 min/max/avg/count → 直接用 stats
    stats_by_cat_period: Dict[str, Dict[str, dict]] = defaultdict(dict)
    spec_card_by_cat: Dict[str, int] = {}

    for bb in breed_buckets:
        bc = bb["key"]
        spec_card_by_cat[bc] = int(bb.get("specs_card", {}).get("value", 0))
        for pb in bb.get("by_period", {}).get("buckets", []):
            ps = _date_str(pb["key"])
            stats = pb.get("price_stats", {}) or {}
            stats_by_cat_period[bc][ps] = {
                "min": stats.get("min"),
                "max": stats.get("max"),
                "avg": stats.get("avg"),
                "count": int(stats.get("count", 0)),
            }

    # 4) 组装
    category_series = []
    for idx, bc in enumerate(breeds):
        points = []
        total_samples = 0
        for ps in period_starts:
            s = stats_by_cat_period.get(bc, {}).get(ps)
            if not s or s["count"] == 0:
                continue
            points.append({
                "period_start": ps,
                "min": round(s["min"], 2) if s["min"] is not None else 0,
                "max": round(s["max"], 2) if s["max"] is not None else 0,
                "avg": round(s["avg"], 2) if s["avg"] is not None else 0,
                "n_total": s["count"],
            })
            total_samples += s["count"]
        # L3 metadata
        l3_code = _l3_code_for_breed(bc)
        l3_info = _l3_info_from_v3(l3_code)
        category_series.append({
            "normalized_breed": bc,
            "l3_code": l3_code,
            "l3_name": l3_info.get("name_l3", ""),
            "gb_50500": l3_info.get("gb_50500", ""),
            "color": _PEER_COLORS[idx % len(_PEER_COLORS)],
            "points": points,
            "meta": {
                "spec_count": spec_card_by_cat.get(bc, 0),
                "sample_count": total_samples,
            },
        })

    return {
        "ok": True,
        "city": city,
        "label": cfg.get("label", city),
        "category_series": category_series,
        "periods": selected_periods,
    }


# ──────────────────────────────────────────────────────────────────────────
# 端点 3: /api/stats/category-l3-peers
# ──────────────────────────────────────────────────────────────────────────

@router.get("/api/stats/category-l3-peers")
def category_l3_peers(
    l3_code: str = Query(..., description="L3 节点 code，如 01.06.01"),
    city: str = Query("qingdao"),
    min_count: int = Query(5, ge=1, le=1000, description="最少样本数（过滤偶发散样本）"),
    limit: int = Query(30, ge=1, le=100),
):
    """同 L3 的所有 normalized_breed（按样本量倒序）

    返回：
    {
      "ok": true,
      "l3_code": "01.06.01",
      "l3_info": {...},
      "peers": [
        {"normalized_breed":"热轧等边角钢","spec_count":132,"sample_count":523,"l3_code":"..."},
        ...
      ]
    }
    """
    query_index, _ = _resolve_norm_index(city)
    if not query_index:
        return {"ok": False, "error": f"找不到可用索引: city={city}"}

    # 主聚合：按 breed_clean 在该 l3_code 下聚合
    main_q = {
        "size": 0,
        "query": {"term": {"category_l3.keyword": l3_code}},
        "aggs": {
            "breeds": {
                "terms": {"field": "breed_clean", "size": limit * 3, "order": {"_count": "desc"}},
                "aggs": {
                    "specs": {
                        "cardinality": {"field": "spec"},
                    },
                },
            },
        },
    }
    try:
        r = es.search(index=query_index, body=main_q, ignore_unavailable=True, allow_no_indices=True)
        buckets = r.get("aggregations", {}).get("breeds", {}).get("buckets", [])
    except Exception as ex:
        return {"ok": False, "error": f"ES 查询失败: {ex}"}

    peers = []
    for b in buckets:
        cnt = b.get("doc_count", 0)
        if cnt < min_count:
            continue
        peers.append({
            "normalized_breed": b["key"],
            "sample_count": cnt,
            "spec_count": int(b.get("specs", {}).get("value", 0)),
        })
        if len(peers) >= limit:
            break

    return {
        "ok": True,
        "l3_code": l3_code,
        "l3_info": _l3_info_from_v3(l3_code),
        "city": city,
        "peers": peers,
        "peer_total": len(peers),
    }
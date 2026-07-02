"""价格走势 API 端点 - 按 period_start 时序聚合某城市某些材料的价格曲线

P1 修复（2026-07-01）：trend 数据"不准"的根因是按 breed 聚合时把所有 spec 的 price 一起算均值
（如闸阀 DN15=20 元 vs DN300=9469 元混算 → 466 倍价差 → 平均值不可信）。
改为按 (breed, spec, unit) 分组聚合，每组单独成一条曲线。

- 临时挂在 provenance_router 上
"""
from fastapi import APIRouter, Query
from elasticsearch import Elasticsearch
import os, sys
from datetime import datetime
from collections import defaultdict, Counter
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


# attr.k 中英映射（前端展示友好）。未识别的 k 原样保留，附 "?"
# 与 gov-price-etl/gov_price_etl/parse_spec/base.py 中的 ATTR_SLOTS 保持一致。
K_LABEL_CN = {
    "grade": "强度",
    "diameter": "直径",
    "type": "类型",
    "length": "长度",
    "width": "宽度",
    "height": "高度",
    "thickness": "厚度",
    "core_count": "芯数",
    "sn_grade": "环刚度",
    "trunk_diameter": "干径",
    "crown_diameter": "冠径",
    "branch_height": "分枝高",
    "mix_grade": "强度等级",
    "strength": "强度",
    "packaging": "包装",
    "natural": "天然",
    "material": "材质",
    "unit_weight": "单重",
    "cross_section": "截面",
    "wall_thickness": "壁厚",
    "spec": "规格",
    "accessory": "配件",
}


def _label_k(k: str) -> str:
    return K_LABEL_CN.get(k, k)


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


def _fetch_all_hits_for_breed(index: str, breed: str, period_starts: list, max_per_breed: int = 50000):
    """按 breed 拉所有 hits（指定 period_start 范围内），用 search_after 翻页

    spec 是 text 类型（无 keyword 子字段），不能直接 terms agg。
    改在 Python 端按 (period_start, spec, unit) 三元组聚合。
    """
    if not period_starts:
        return []
    all_hits = []
    pit = None
    page_size = 5000
    query = {
        "bool": {
            "must": [{"term": {"breed": breed}}],
            "filter": [{"terms": {"period_start": period_starts}}],
        }
    }
    sort = [{"period_start": "asc"}, {"_id": "asc"}]
    try:
        if pit is None:
            pit = es.open_point_in_time(index=index, keep_alive="2m", ignore_unavailable=True)["id"]
        while True:
            body = {
                "size": page_size,
                "query": query,
                "sort": sort,
                "pit": {"id": pit, "keep_alive": "2m"},
                "_source": ["period_start", "spec", "attr", "unit", "price"],
            }
            r = es.search(body=body, ignore_unavailable=True)
            hits = r.get("hits", {}).get("hits", [])
            if not hits:
                break
            all_hits.extend(hits)
            if len(hits) < page_size:
                break
            if len(all_hits) >= max_per_breed:
                break
            pit = r.get("pit_id", pit)
        try:
            es.close_point_in_time(id=pit)
        except Exception:
            pass
    except Exception:
        # 回退：单次拉 size=10000（无 PIT）
        try:
            r = es.search(
                index=index,
                body={
                    "size": min(max_per_breed, 10000),
                    "query": query,
                    "sort": sort,
                    "_source": ["period_start", "spec", "attr", "unit", "price"],
                },
                ignore_unavailable=True,
            )
            all_hits = r.get("hits", {}).get("hits", [])
        except Exception:
            all_hits = []
    return all_hits


def _aggregate_hits_by_attr(hits, selected_periods):
    """按 attr 维度聚合 hits（v3 - 用 attr 代替 spec 字符串）

    优先级：
      1. 文档有 attr 数组 → 每个 attr 项独立算时序一条曲线（key='attr.k=attr.v'）
         如 grade=C20、diameter=50。一条文档有 3 个 attr 项 → 贡献 3 条曲线
      2. 文档无 attr（少数）→ fallback 到 spec 字符串（key='__spec__=原文'）
    这样相同语义但 spec 写法不同（如 'DN50' vs 'DN 50'）会按 attr 同维度自动合并。

    返回：
    {
      'specs': [
        {
          'spec': 'grade=C20',       # 前端展示名
          'attr_key': 'grade',         # attr.k 或 '__spec__'（fallback）
          'attr_val': 'C20',           # attr.v 或 spec 原文
          'unit': '',                  # 用 attr 维度后 unit 在多曲线上不唯一
          'n_total': N,
          'points': [...]
        }, ...
      ],
      'overall_points': [...],   # 兼容：跨 attr 整体均价
      'units_seen': [...],
    }
    """
    # key: (attr_k, attr_v) -> {period_start: [prices]}
    grp = defaultdict(lambda: defaultdict(list))
    overall_by_period = defaultdict(list)
    units_count = Counter()
    for h in hits:
        src = h.get("_source", {}) or {}
        ps = _date_str(src.get("period_start"))
        if not ps:
            continue
        price = src.get("price")
        if price is None:
            continue
        unit = src.get("unit") or ""
        attrs = src.get("attr") or []
        if attrs:
            for a in attrs:
                k = (a.get("k") or "").strip()
                v = (a.get("v") or "").strip()
                if not k or not v:
                    continue
                grp[(k, v)][ps].append(price)
        else:
            # fallback：attr 缺失则用 spec 字符串作为聚合 key
            spec_raw = (src.get("spec") or "").strip()
            grp[("__spec__", spec_raw or "__通用__")][ps].append(price)
        overall_by_period[ps].append(price)
        units_count[unit] += 1

    def _points(by_period_dict):
        out = []
        for p in selected_periods:
            prices = by_period_dict.get(p["start"])
            if not prices:
                continue
            out.append({
                "period_start": p["start"],
                "period_end": p.get("end", ""),
                "avg": round(sum(prices) / len(prices), 2),
                "min": round(min(prices), 2),
                "max": round(max(prices), 2),
                "n": len(prices),
            })
        return out

    specs_out = []
    main_unit = units_count.most_common(1)[0][0] if units_count else ""
    for (k, v), by_period in grp.items():
        pts = _points(by_period)
        if not pts:
            continue
        n_total = sum(p["n"] for p in pts)
        if k == "__spec__":
            label = v           # fallback 时直接显示 spec 原文
        else:
            label = f"{_label_k(k)}={v}"  # attr 维度时显示 '中文k=v'（如 强度=C20）
        specs_out.append({
            "spec": label,
            "attr_key": k,
            "attr_val": v,
            "unit": main_unit,
            "n_total": n_total,
            "points": pts,
        })
    specs_out.sort(key=lambda x: (-x["n_total"], x["spec"]))

    overall_points = _points(overall_by_period)
    return {
        "specs": specs_out,
        "overall_points": overall_points,
        "units_seen": [u for u, _ in units_count.most_common()],
    }


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
    top_specs: int = Query(5, ge=1, le=20, description="每个材料返回的 spec 数（按样本量倒序）"),
    max_breeds: int = Query(30, ge=1, le=100, description="materials=* 时取 top N 材料（按文档数倒序）"),
    attr_keys: str = Query("", description="过滤 attr_key，逗号分隔；空表示不过滤（返回所有 attr_key）"),
):
    """返回 city 索引下，每个材料 × 每个规格按 period_start 时序的均价/最小/最大/数量

    返回结构（v2 - 按 spec 拆分）：
    {
      "ok": true,
      "city": "qingdao", "label": "青岛",
      "granularity": "monthly",
      "periods": [{"start": "2026-02-01", "end": "2026-02-28", "label": "2026年02月"}, ...],
      "series": [
        {
          "material": "闸阀",
          "unit": "个",                    // 兼容字段：主要 unit
          "spec_count": 12,                // 该材料总共多少个 spec
          "n_total": 3096,                 // 该材料总样本
          "specs": [                       // top N 个 spec
            {
              "spec": "DN50",
              "unit": "个",
              "n_total": 327,
              "points": [{"period_start": "2026-04-01", "avg": 320.5, "min": 300, "max": 340, "n": 5}, ...]
            },
            ...
          ],
          "points": [...],                 // 兼容字段：跨 spec 整体均价（旧逻辑，标注 ⚠混合口径）
        },
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
        selected_periods = selected_periods[-periods:]
    else:
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
                "aggs": {"b": {"terms": {"field": "breed", "size": max_breeds, "order": {"_count": "desc"}}}},
            },
            ignore_unavailable=True,
        )
        mat_list = [b["key"] for b in agg_r.get("aggregations", {}).get("b", {}).get("buckets", [])]
    else:
        mat_list = [m.strip() for m in materials.split(",") if m.strip()]

    # 4) 按材料拉 hits → 按 (spec, unit) 聚合
    series = []
    period_starts = [p["start"] for p in selected_periods]
    for mat in mat_list:
        hits = _fetch_all_hits_for_breed(dws_index, mat, period_starts)
        if not hits:
            series.append({
                "material": mat,
                "unit": "",
                "spec_count": 0,
                "n_total": 0,
                "specs": [],
                "points": [],
            })
            continue
        agg = _aggregate_hits_by_attr(hits, selected_periods)
        all_specs = agg["specs"]
        # attr_keys 过滤：用户只选某些 attr_key 时过滤（空 = 不过滤）
        # __spec__ 是 fallback 使用的 key（attr 缺失文档）
        if attr_keys.strip():
            keys_set = {k.strip() for k in attr_keys.split(",") if k.strip()}
            all_specs = [s for s in all_specs if s["attr_key"] in keys_set]
        specs = all_specs[:top_specs]
        # available_attr_keys：本材料下出现过的 attr_key 列表，供前端 chip 过滤器使用
        seen_keys = []
        seen_keys_set = set()
        for s in agg["specs"]:
            k = s["attr_key"]
            if k not in seen_keys_set:
                seen_keys_set.add(k)
                seen_keys.append(k)
        series.append({
            "material": mat,
            "unit": agg["units_seen"][0] if agg["units_seen"] else "",
            "spec_count": len(agg["specs"]),
            "n_total": sum(p["n"] for p in agg["overall_points"]),
            "specs": specs,
            "available_attr_keys": [{"key": k, "label": _label_k(k)} for k in seen_keys],
            "points": agg["overall_points"],
        })

    # 5) total_docs
    total = es.count(
        index=dws_index,
        body={"query": {"terms": {"period_start": period_starts}}},
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
        "top_specs": top_specs,
    }
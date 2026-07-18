"""价格走势 API 端点 - 按 period_start 时序聚合某城市某些材料的价格曲线

P1 修复（2026-07-01）：trend 数据"不准"的根因是按 breed 聚合时把所有 spec 的 price 一起算均值
（如闸阀 DN15=20 元 vs DN300=9469 元混算 → 466 倍价差 → 平均值不可信）。
改为按 (breed, spec, unit) 分组聚合，每组单独成一条曲线。

- 临时挂在 provenance_router 上
"""
from fastapi import APIRouter, Query
from elasticsearch import Elasticsearch
import os, sys
import re
import unicodedata
from datetime import datetime
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api.skill_registry import get as _registry_get

router = APIRouter()
ES_HOST = os.environ.get("ES_HOST", "http://localhost:59200")
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


# attr.k 中英映射（前端展示友好）。未识别的 k 原样保留，附 "(k)"
# 三层加载：
#   1) 权威基础：自动从 gov-price-etl/gov_price_etl/parse_spec/rules/_attrs.py 读取
#   2) 兼容 alias：覆盖 ETL 历史别名的差异（如 cores ↔ core_count）
#   3) 海南扩展：实际 DWS 写入但 _attrs.py 未定义的园林景观/玻璃/塑钢类
def _load_attr_label_cn() -> dict:
    """从规格规则库 + 城市扩展加载 attr_key 中文标签。"""
    import re
    from pathlib import Path
    labels = {}

    # 1) 权威基础：gov-price-etl/gov_price_etl/parse_spec/rules/_attrs.py
    #    trend.py 位于 skills/gov-price-dashboard/api/routes/trend.py
    #    routes/ → api/ → dashboard/ → skills/ (4 .parent)
    #    工作区根目录即为 skills/，gov-price-etl 在其下并列。
    try:
        attrs_path = (
            Path(__file__).resolve().parent.parent.parent.parent
            / "gov-price-etl"
            / "gov_price_etl" / "parse_spec" / "rules" / "_attrs.py"
        )
        if attrs_path.exists():
            content = attrs_path.read_text(encoding="utf-8")
            arrow = chr(0x2192)  # →
            for raw in content.split("\n"):
                line = raw.strip()
                if not line or line.startswith("#") or arrow not in line:
                    continue
                left, right = line.split(arrow, 1)
                keys = re.findall(r'"(\w+)"', left)
                cns = re.findall(r'"([^"]+)"', right)
                if keys and cns:
                    labels.setdefault(keys[0], cns[0])
    except Exception:
        pass

    # 2) 兼容 alias（_attrs.py 已存在的 key 不覆盖；只补缺）
    aliases = {
        # ETL 历史别名
        "core_count": "芯数",           # _attrs.py 是 "cores"，ETL 也产出 core_count
        "cross_section_area": "截面面积",  # _attrs.py 是 "cross_section"（电缆截面）
        "pe_core_count": "PE 芯数",
        "pe_cross_section": "PE 截面",
        "sn_grade": "环刚度",            # _attrs.py 是 "ring_stiffness"
        "strength": "强度",
        "mix_grade": "强度等级",
        # 同义但 label 更口语
        "grade": "强度/标号",
        "trunk_diameter": "干径",
        "crown_diameter": "冠径",
        "branch_height": "分枝高",
    }
    for k, v in aliases.items():
        labels.setdefault(k, v)

    # 3) 海南扩展（实际 DWS 数据里有，_attrs.py 暂未收）
    #    - 苗木类（重庆/海南园林景观）
    #    - 玻璃门窗类（海南含装饰装修材料）
    #    - 通用工程类（_attrs.py 已含基础 32 个的 *_range 衍生）
    hainan_extras = {
        # ─ 苗木/景观 ─
        "trunk_diameter_range": "干径范围",
        "crown_width_range": "冠幅范围",
        "branch_diameter_range": "分枝径范围",
        "palm_height": "株高",
        # ─ 玻璃/门窗/装饰 ─
        "glass_thickness": "玻璃厚度",
        "glass_thickness_left": "玻璃厚度(左)",
        "glass_thickness_right": "玻璃厚度(右)",
        "interlayer_thickness": "夹层厚度",
        "tempering": "钢化",
        "fabric_type": "织物类型",
        # ─ 通用扩展（_attrs.py 缺 *_range） ─
        "thickness_range": "厚度范围",
        "width_range": "宽度范围",
        "diameter_range": "直径范围",
        "grade_range": "强度范围",
        "area_range": "面积范围",
        "depth_range": "深度范围",
        "wall_thickness_range": "壁厚范围",
        "container_size": "容器规格",
        "container_type": "容器类型",
        "surface": "表面处理",
        "reinforcement_content": "含筋量",
        "density": "密度",
        "usage": "用途",
        "quantity": "数量",
        "spacing": "间距",
        "feature": "特性",
        # ─ ETL 错位 / 业务特别 ─
        "type": "类型",
        "spec": "规格",
        "unit_weight": "单重",
        "natural": "天然",
        "packaging": "包装",
        "accessory": "配件",
        # 兜底（不应出现在 attr.k，_attrs.py 也无；标以中文避免英文飘红）
        "breed": "品种",
        "unit": "单位",
    }
    for k, v in hainan_extras.items():
        labels.setdefault(k, v)

    # 4) DWS 实际数据补全（2026-07-05 修复：trend 页 chip 拆分维度仍残留英文）
    #    覆盖 17 城 dws_*_price 索引里实际出现但上面三类未定义的 attr.k。
    dws_extras = {
        # ─ 物理/几何 ─
        "outer_diameter": "外径",
        "inner_thickness": "内厚",
        "short_leg_width": "短边宽",
        "long_leg_width": "长边宽",
        "web_thickness": "腹板厚度",
        "flange_thickness": "翼缘厚度",
        "flange_type": "翼缘形式",
        "small_diameter": "小径",
        "volume": "体积",
        "distance": "距离",
        "angle": "角度",
        "cut_angle": "切口角度",
        # ─ 颗粒/筛分/配合比 ─
        "particle_size": "粒径",
        "particle_size_max": "最大粒径",
        "particle_size_min": "最小粒径",
        "particle_size_range": "粒径范围",
        "mesh_size": "筛孔尺寸",
        "mix_ratio": "配合比",
        "concentration": "浓度",
        # ─ 苗木/景观 ─
        "branch_diameter": "分枝径",
        "branch_diameter_max": "最大分枝径",
        "branch_diameter_min": "最小分枝径",
        "branch_count": "分枝数",
        "branch_count_range": "分枝数范围",
        "single_branch_length": "单枝长",
        "trunk_count": "主干数",
        "pot_diameter": "盆径",
        "crown_width": "冠幅",
        "growth_period": "生长周期",
        "bud_count": "芽数",
        "leaf_count": "叶数",
        # ─ 电/电伴热 ─
        "power": "功率",
        "power_range": "功率范围",
        "output_voltage": "输出电压",
        "frequency": "频率",
        "backup_time": "备用时间",
        "light_source": "光源",
        "voltage_range": "电压范围",
        "voltage_rating": "电压等级",
        "temperature_rating": "温度等级",
        # ─ 防水/管材/材料 ─
        "fire_resistance": "耐火极限",
        "surface_type": "表面类型",
        "coating": "涂层",
        "socket_type": "套接形式",
        "outlet_count": "出水口数",
        "sleeve_count": "套筒数",
        "layer_count": "层数",
        "flow_coefficient": "流量系数",
        "interlayer_material": "夹层材质",
        "glass_type": "玻璃类型",
        # ─ 通用 ─
        "model": "型号",
        "brand": "品牌",
        "standard": "标准",
        "code": "编号",
        "origin": "产地",
        "plant_spec": "苗木规格",
        "process": "工艺",
        "structure": "结构",
        "capacity": "容量",
        "air_volume": "风量",
        "humidity": "湿度",
        "duration_max": "最长时间",
        "duration_min": "最短时间",
        "base_type": "基层类型",
        "material_type": "材质类型",
        "pole_count": "杆数",
        "glass": "玻璃",
        "washing_method": "洗涤方式",
        "water_absorption": "吸水率",
        "water_repellency": "防水性",
        "softening_rate": "软化率",
        "price_range": "价格区间",
        "cross_section_range": "截面范围",
    }
    for k, v in dws_extras.items():
        labels.setdefault(k, v)

    return labels


K_LABEL_CN = _load_attr_label_cn()

# 后端 attr 聚合用的 fallback sentinel 键名，在 K_LABEL_CN 里查不到，
# 这里给一个可读中文标签（前端 chip + spec 列展示都不再出现 "__spec__"）。
#   __spec__    : 文档 attr=[] 但 spec 字符串还在 — 以 spec 原文作为唯 一维度
#   __general__ : 文档 attr=[] 且 spec='' — 完全无规格信息
_ATTR_KEY_SPECIAL = {
    "__spec__":    "原文规格",
    "__general__": "通用规格",
}


def _label_k(k: str) -> str:
    if k in _ATTR_KEY_SPECIAL:
        return _ATTR_KEY_SPECIAL[k]
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
    # 跨城 join: normalized_breed 优先，breed 兑底（兼容老 NORM 索引）
    query = {
        "bool": {
            "must": [
                {
                    "bool": {
                        "should": [
                            {"term": {"normalized_breed.keyword": breed}},
                            {"term": {"breed": breed}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
            ],
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
        description="逗号分隔的 normalized_breed 列表；* 表示取该城市 top 30"
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
          "normalized_breed": "闸阀",
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

    # 注：price_trend 不接 breed 入参（旧 patch 把 compare 函数的归一化块误粘了进来，
    #     会导致 UnboundLocalError）。aggs 那边 line 558 已经改为按 normalized_breed.keyword 聚合，
    #     故此处不再做 per-call normalize。
    # NORM 优先查询：DWS → NORM 自动 fallback
    from api.normalization_bridge import resolve_query_index
    _idx_res = resolve_query_index(es, city, prefer="norm")
    query_index = _idx_res["index"]
    if not query_index:
        return {"ok": False, "error": f"DWS 和 NORM 索引都不存在: city={city}"}

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
        ap = es.search(index=query_index, body=all_periods_q, ignore_unavailable=True)
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
            "index_used": query_index,
            "dws_index": dws_index,
            "norm_index": f"norm_{city}_price",
            "index_fallback": _idx_res["fallback"],
            "index_reason": _idx_res["reason"],
            "granularity": granularity,
            "periods": [],
            "series": [],
        }

    # 3) 拉材料列表
    if not materials or materials.strip() in ("*", "all", "ALL"):
        agg_r = es.search(
            index=query_index,
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

    # 4) 按材料拉 hits → 按 (spec, unit) 聚合
    series = []
    period_starts = [p["start"] for p in selected_periods]
    for mat in mat_list:
        hits = _fetch_all_hits_for_breed(query_index, mat, period_starts)
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
            "normalized_breed": mat,
            "unit": agg["units_seen"][0] if agg["units_seen"] else "",
            "spec_count": len(agg["specs"]),
            "n_total": sum(p["n"] for p in agg["overall_points"]),
            "specs": specs,
            "available_attr_keys": [{"key": k, "label": _label_k(k)} for k in seen_keys],
            "points": agg["overall_points"],
        })

    # 5) total_docs
    total = es.count(
        index=query_index,
        body={"query": {"terms": {"period_start": period_starts}}},
        ignore_unavailable=True,
    ).get("count", 0)

    return {
        "ok": True,
        "city": city,
        "label": cfg.get("label", city),
        "index_used": query_index,                    # 实际查的索引（NORM 优先，DWS fallback）
        "dws_index": dws_index,                        # 原始 DWS 索引名（保留向后兼容）
        "norm_index": f"norm_{city}_price",           # 期望的 NORM 索引名
        "index_fallback": _idx_res["fallback"],       # True = 走了 fallback
        "index_reason": _idx_res["reason"],
        "granularity": granularity,
        "periods": selected_periods,
        "series": series,
        "total_docs": total,
        "top_specs": top_specs,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 跨城市价格对比 API
#
# 用途：在 trend 页面"横向看 N 个城市 同 品种 同 规格" 的价格走势。
# 数据源：每个城市的 dws_{city}_price 索引（DWS 层，结构统一）。
# 设计要点：
#   1. 多 DWS 索引并行查询（ThreadPoolExecutor）
#   2. spec 对齐：attr (k=v) 拼接为 spec_key（首选），spec 字符串归一化兜底
#   3. unit 约束：可强约束同单位（防 元/吨 vs 元/根）
#   4. period 对齐：取所有城市 period_start 的并集，缺的置 null（折线断点）
#   5. unit 智能回退：若指定 unit 找不到匹配，自动选各城市样本数最多的单位（并标注）
# ─────────────────────────────────────────────────────────────────────────────

# 各省色（每城市用所属省的颜色，在芯片 + 折线 + 表格里统一）
_PROVINCE_COLOR = {
    "陕西": "#dc2626", "西安": "#dc2626",
    "四川": "#2563eb", "成都": "#2563eb",
    "重庆": "#16a34a",
    "山东": "#ea580c", "济南": "#ea580c", "日照": "#ea580c", "菏泽": "#ea580c", "青岛": "#ea580c", "威海": "#ea580c",
    "河南": "#7c3aed",
    "湖南": "#0891b2",
    "江西": "#db2777",
    "宁夏": "#65a30d",
    "青海": "#9333ea",
    "新疆": "#0d9488",
    "内蒙古": "#e11d48",
    "海南": "#4f46e5",
}

# spec 字符串归一化（φ → phi，Φ → phi，去空白，unicode NFKC）
_PHI_RE = re.compile(r"[\u03c6\u03a6\u2300\u00d8\u00f8]")


def _norm_spec_str(s: str) -> str:
    """spec 字符串归一化：用于跨城市 spec fallback 对齐"""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = _PHI_RE.sub("phi", s)
    s = s.replace("×", "x").replace("X", "x")
    s = re.sub(r"\s+", "", s)
    s = s.lower()
    return s


def _build_attr_spec_key(attrs) -> str:
    """从 [{k,v}, ...] 构造 attr-based spec_key：'diameter=20|grade=HRB400'"""
    if not attrs:
        return ""
    pairs = sorted([(a.get("k", "").strip(), a.get("v", "").strip())
                    for a in attrs if a.get("k") and a.get("v")])
    if not pairs:
        return ""
    return "|".join(f"{k}={v}" for k, v in pairs)


def _align_spec(rec: dict) -> tuple:
    """对单条记录返回 (spec_key, spec_label, align_method)
    - 优先级：attr-based → spec 归一化
    - spec_label 优先中文 attr 标签（如「直径=20」），后是 spec 原文
    """
    attrs = rec.get("attr") or []
    attr_key = _build_attr_spec_key(attrs)
    if attr_key:
        # 用 _label_k 把 attr key 转中文标签供展示用
        labels = []
        for a in attrs:
            k = (a.get("k") or "").strip()
            v = (a.get("v") or "").strip()
            if k and v:
                cn = _label_k(k) or k
                labels.append(f"{cn}={v}")
        return attr_key, " / ".join(labels[:3]), "attr"
    spec_raw = (rec.get("spec") or "").strip()
    if spec_raw:
        return _norm_spec_str(spec_raw), spec_raw, "spec_norm"
    return "__general__", "（通用规格）", "fallback"


def _pick_unit(unit_constraint: str, hits_by_unit: Counter) -> str:
    """用户指定 unit_constraint 直接返回；否则选样本最多的单位"""
    if unit_constraint:
        return unit_constraint
    if not hits_by_unit:
        return ""
    return hits_by_unit.most_common(1)[0][0]


@router.get("/api/stats/price-trend-compare")
def price_trend_compare(
    breed: str = Query(..., description="必选品种名"),
    cities: str = Query(..., description="逗号分隔的城市 key，最多 6 个"),
    unit: str = Query("", description="可选 unit 约束（防止 元/吨 vs 元/根 比较）"),
    spec_filter: str = Query("", description="可选 attr 过滤 'k1=v1,k2=v2'，逗号分隔"),
    periods: int = Query(12, ge=1, le=60, description="取最近 N 个业务期"),
    date_from: str = Query("", description="起始期 YYYY-MM-DD，优先于 periods"),
    date_to: str = Query("", description="结束期 YYYY-MM-DD"),
    top_specs: int = Query(3, ge=1, le=10, description="每城市返回的 spec_group 数（按样本量）"),
    align: str = Query("attr_first", description="attr_first | spec_first | hybrid"),
):
    """跨城市价格对比（同品种 × N 城市）。

    返回结构：
    {
      "ok": true,
      "breed": "HRB400",
      "cities": [{"key":"xian","label":"西安","color":"#dc2626","dws_index":"dws_xian_price"}, ...],
      "aligned_periods": [{"start":"2026-01","end":"2026-01","label":"2026年01月"}, ...],
      "series": [
        {
          "city":"xian","label":"西安","color":"#dc2626",
          "unit_used":"t","unit_fallback":false,
          "n_total":320,
          "spec_groups":[
            {
              "spec_key":"diameter=20|grade=HRB400",
              "spec_label":"直径=20 / 强度=HRB400",
              "align_method":"attr",
              "n_total":100,
              "points":[{"period_start":"2026-01","avg":3450,"min":3400,"max":3500,"n":5}, ...],
              "missing_periods":[]
            }
          ]
        }
      ],
      "overall": {  // 全城市同期均价对比（不管 spec，仅 unit 过滤）
        "by_period":[{"period_start":"2026-01","by_city":[{"city":"xian","avg":3450,"n":5}]}, ...]
      }
    }
    """
    from api.skill_registry import get as _registry_get

    # 归一化入参 breed（与 price_trend 一致）
    from api.normalization_bridge import normalize_breed_text
    if breed:
        breed_orig = breed
        breed = normalize_breed_text(breed)
        if breed != breed_orig:
            print(f"[breed normalize compare] {breed_orig!r} → {breed!r}")

    # 1. 解析城市列表
    city_keys = [c.strip() for c in cities.split(",") if c.strip()]
    if not city_keys:
        return {"ok": False, "error": "cities 不能为空"}
    if len(city_keys) > 6:
        return {"ok": False, "error": "最多 6 个城市"}

    city_cfgs = []
    for ck in city_keys:
        cfg = _registry_get(ck) or {}
        if not cfg.get("dws_index"):
            return {"ok": False, "error": f"未知城市或无 DWS 索引: {ck}"}
        # NORM 优先 + DWS fallback
        from api.normalization_bridge import resolve_query_index
        _idx_res = resolve_query_index(es, ck, prefer="norm")
        city_cfgs.append({
            "key": ck,
            "label": cfg.get("label", ck),
            "color": _PROVINCE_COLOR.get(cfg.get("label", ck), _PROVINCE_COLOR.get(cfg.get("province", ""), "#64748b")),
            "dws_index": cfg["dws_index"],
            "query_index": _idx_res["index"],       # 实际查的索引
            "index_fallback": _idx_res["fallback"],
            "province": cfg.get("province", ""),
        })
    # 在响应顶层附上每个城市的 fallback 情况（方便前端提示）
    city_index_status = {
        c["key"]: {
            "query_index": c["query_index"],
            "index_fallback": c["index_fallback"],
            "reason": "norm_preferred" if not c["index_fallback"] else "norm_missing_fallback_dws",
        }
        for c in city_cfgs
    }

    # 2. 解析 spec_filter
    spec_filter_pairs = []
    if spec_filter.strip():
        for kv in spec_filter.split(","):
            kv = kv.strip()
            if "=" in kv:
                k, v = kv.split("=", 1)
                spec_filter_pairs.append((k.strip(), v.strip()))

    # 3. 并行查询各城市的全部 (period_start × spec × unit × price)
    # 跨城 join: normalized_breed 优先，breed 兑底
    query = {
        "bool": {
            "must": [
                {
                    "bool": {
                        "should": [
                            {"term": {"normalized_breed.keyword": breed}},
                            {"term": {"breed": breed}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
            ],
            "filter": ([{"term": {"unit": unit}}] if unit else []),
        }
    }

    def fetch_city(cfg):
        """查一个城市：按 (period_start, spec_key, unit) 聚合"""
        idx = cfg["query_index"]   # NORM 优先，缺失 fallback DWS
        city_result = {
            "city": cfg["key"], "label": cfg["label"], "color": cfg["color"],
            "dws_index": idx,
            "hits_by_unit": Counter(),
            "spec_groups": defaultdict(lambda: defaultdict(list)),  # spec_key -> period_start -> [price]
            "n_total": 0,
        }
        try:
            # 加 period_start date range（若有）
            q_with_date = query
            if date_from or date_to:
                date_range = {}
                if date_from:
                    date_range["gte"] = date_from
                if date_to:
                    date_range["lte"] = date_to
                q_with_date = {
                    "bool": {
                        "must": query["bool"].get("must", []),
                        "filter": query["bool"].get("filter", []) + [
                            {"range": {"period_start": date_range}}
                        ],
                    }
                }

            # size=10000 单查询（同品种同期一般不会超）。超出走 scroll。
            r = es.search(
                index=idx,
                body={
                    "size": 10000,
                    "query": q_with_date,
                    "sort": [{"period_start": "asc"}],
                    "_source": ["period_start", "spec", "attr", "unit", "price"],
                },
                ignore_unavailable=True,
                allow_no_indices=True,
            )
            all_hits = r.get("hits", {}).get("hits", [])
            total = r.get("hits", {}).get("total", {}).get("value", 0)

            # 超过 10k 走 scroll 补
            if total > 10000:
                try:
                    sid = es.open_scroll(
                        scroll="2m", index=idx,
                        body={"query": q_with_date, "size": 5000},
                    )["_scroll_id"]
                    while True:
                        sr = es.scroll(scroll="2m", body={"scroll_id": sid, "scroll": "2m"})
                        sh = sr.get("hits", {}).get("hits", [])
                        if not sh:
                            break
                        all_hits.extend(sh)
                        if len(sh) < 5000:
                            break
                        sid = sr.get("_scroll_id", sid)
                    try:
                        es.clear_scroll(scroll_id=sid)
                    except Exception:
                        pass
                except Exception as _se:
                    print(f"[compare] scroll fallback for {idx}: {_se}")
        except Exception as _e:
            print(f"[compare] fetch_city {cfg['key']}: {_e}")
            all_hits = []

        # 聚合
        period_set = set()
        spec_label_map = {}
        spec_align_method = {}
        attr_keys_seen = set()
        for h in all_hits:
            src = h.get("_source", {}) or {}
            ps = src.get("period_start")
            if not ps:
                continue
            price = src.get("price")
            if price is None:
                continue
            u = (src.get("unit") or "").strip()

            # spec_filter 过滤（attr 维度）
            attrs = src.get("attr") or []
            if spec_filter_pairs:
                attr_kv = {(a.get("k") or "").strip(): (a.get("v") or "").strip()
                           for a in attrs if a.get("k") and a.get("v")}
                if not all(attr_kv.get(k) == v for k, v in spec_filter_pairs):
                    continue

            # spec 对齐
            spec_key, spec_label, method = _align_spec(src)
            if spec_key == "__general__":
                continue

            city_result["spec_groups"][spec_key][ps].append(float(price))
            spec_label_map.setdefault(spec_key, spec_label)
            spec_align_method.setdefault(spec_key, method)
            for a in attrs:
                k = (a.get("k") or "").strip()
                if k:
                    attr_keys_seen.add(k)
            city_result["hits_by_unit"][u] += 1
            city_result["n_total"] += 1
            period_set.add(ps[:10] if isinstance(ps, str) else str(ps)[:10])

        # 输出格式：top_specs 过滤
        sorted_spec_keys = sorted(
            city_result["spec_groups"].keys(),
            key=lambda k: sum(len(v) for v in city_result["spec_groups"][k].values()),
            reverse=True,
        )[:top_specs]

        spec_groups_out = []
        for sk in sorted_spec_keys:
            by_period = city_result["spec_groups"][sk]
            pts = []
            for ps, prices in by_period.items():
                if not prices:
                    continue
                pts.append({
                    "period_start": ps,
                    "avg": round(sum(prices) / len(prices), 2),
                    "min": round(min(prices), 2),
                    "max": round(max(prices), 2),
                    "n": len(prices),
                })
            pts.sort(key=lambda x: x["period_start"])
            spec_groups_out.append({
                "spec_key": sk,
                "spec_label": spec_label_map.get(sk, sk),
                "align_method": spec_align_method.get(sk, "attr"),
                "n_total": sum(p["n"] for p in pts),
                "points": pts,
            })

        # unit 智能选择（用户未指定时按样本最多）
        unit_used = _pick_unit(unit, city_result["hits_by_unit"])
        unit_fallback = (not unit) and bool(city_result["hits_by_unit"])

        return {
            "city": cfg["key"],
            "label": cfg["label"],
            "color": cfg["color"],
            "dws_index": idx,
            "periods_seen": sorted(period_set),
            "unit_used": unit_used,
            "unit_fallback": unit_fallback,
            "n_total": city_result["n_total"],
            "spec_groups": spec_groups_out,
            "attr_keys_seen": sorted(attr_keys_seen),
        }

    # 并发拉所有城市（最多 6 个城市，4 线程足够）
    results_by_city = {}
    with ThreadPoolExecutor(max_workers=min(len(city_cfgs), 4)) as pool:
        futures = {pool.submit(fetch_city, c): c["key"] for c in city_cfgs}
        for f in as_completed(futures):
            r = f.result()
            results_by_city[r["city"]] = r

    # 4. 拼返回结构，按调用顺序排序
    series_out = []
    for cfg in city_cfgs:
        r = results_by_city.get(cfg["key"]) or {
            "city": cfg["key"], "label": cfg["label"], "color": cfg["color"],
            "periods_seen": [], "unit_used": "", "unit_fallback": False,
            "n_total": 0, "spec_groups": [], "attr_keys_seen": [],
        }
        # 计算 missing_periods：相对其他城市的并集看缺口（粗略，只提示哪些期没数据）
        series_out.append(r)

    # 5. 计算 aligned_periods（所有城市 period_start 的并集，按时间升序，最多 periods 期）
    all_periods = set()
    period_labels = {}
    for r in series_out:
        for p in r["periods_seen"]:
            all_periods.add(p)
            period_labels.setdefault(p, _period_label(p, "monthly"))
    aligned = sorted(all_periods)
    if date_from:
        aligned = [p for p in aligned if p >= date_from]
    if date_to:
        aligned = [p for p in aligned if p <= date_to]
    aligned = aligned[-periods:]  # 取最近 N 期

    aligned_periods = [
        {"start": p, "end": p, "label": period_labels.get(p, _period_label(p, "monthly"))}
        for p in aligned
    ]

    # 6. 给每个城市的 spec_group 补 missing_periods 标记
    aligned_set = set(aligned)
    for r in series_out:
        present_set = set(r["periods_seen"])
        miss = sorted(aligned_set - present_set)
        r["missing_periods"] = miss

    # 7. 整体同期均价对比（overall）
    overall = {
        "by_period": [],
        "by_unit": unit or "",
    }
    for p in aligned:
        row = {"period_start": p, "by_city": []}
        for r in series_out:
            # 取该城市全部 spec_groups 在该期的价格汇聚
            prices = []
            for sg in r["spec_groups"]:
                for pt in sg["points"]:
                    if pt["period_start"] == p:
                        # 复用 avg，避免重新计算（avg 已聚合过一组价格）
                        # 但 spec filter 同 unit 下价格跨度可能过大，overall 仅参考用
                        prices.append(pt["avg"])
            if prices:
                row["by_city"].append({
                    "city": r["city"], "label": r["label"], "color": r["color"],
                    "avg": round(sum(prices) / len(prices), 2),
                    "n": len(prices),
                })
        overall["by_period"].append(row)

    # 8. 跨城 spec 关键词（attr 维度）排序，给前端"拆分维度"建议
    cross_attr_keys = []
    attr_counter = Counter()
    for r in series_out:
        for k in r["attr_keys_seen"]:
            attr_counter[k] += 1
    for k, cnt in attr_counter.most_common(15):
        cross_attr_keys.append({"key": k, "label": _label_k(k), "cities_with_it": cnt})

    # 9. 价差走势（spread）— 按对齐期聚合 max/min/spread/spread_pct
    #      spread_pct = (max - min) / mid * 100，mid = 当期均值
    #      - spread_overall_by_period：整品种跨城聚合（来源 overall.by_city）
    #      - spread_by_spec：每个 spec_key 跨城在每期的 max/min，并标注 max_city/min_city
    spread_overall_by_period = []
    for row in overall["by_period"]:
        bcities = row["by_city"]
        if len(bcities) < 2:
            # 单城无法计算 spread；返回 max=min=该城均价，便于绘图留空
            spread_overall_by_period.append({
                "period_start": row["period_start"],
                "label": period_labels.get(row["period_start"], row["period_start"]),
                "max": round(bcities[0]["avg"], 2) if bcities else None,
                "min": round(bcities[0]["avg"], 2) if bcities else None,
                "spread": 0.0,
                "spread_pct": 0.0,
                "max_city": bcities[0]["city"] if bcities else None,
                "min_city": bcities[0]["city"] if bcities else None,
                "n_cities": len(bcities),
            })
            continue
        vals = [(c["avg"], c["city"]) for c in bcities]
        vmax = max(vals, key=lambda x: x[0])
        vmin = min(vals, key=lambda x: x[0])
        spread = vmax[0] - vmin[0]
        mid = sum(v for v, _ in vals) / len(vals)
        spread_overall_by_period.append({
            "period_start": row["period_start"],
            "label": period_labels.get(row["period_start"], row["period_start"]),
            "max": round(vmax[0], 2),
            "min": round(vmin[0], 2),
            "spread": round(spread, 2),
            "spread_pct": round((spread / mid) * 100, 2) if mid else 0.0,
            "max_city": vmax[1],
            "min_city": vmin[1],
            "n_cities": len(bcities),
        })

    # spec_key 级别的价差（用于后续 per-spec 价差走势 small multiples）
    spread_by_spec = []
    all_spec_keys: dict = {}
    for r in series_out:
        for sg in r["spec_groups"]:
            all_spec_keys.setdefault(sg["spec_key"], {
                "spec_key": sg["spec_key"],
                "spec_label": sg["spec_label"],
                "align_method": sg["align_method"],
            })
    for sk, info in all_spec_keys.items():
        by_period = []
        for ap in aligned_periods:
            ps = ap["start"]
            # 收集该 spec_key 在该期的所有城市点
            pts = []
            for r in series_out:
                for sg in r["spec_groups"]:
                    if sg["spec_key"] != sk:
                        continue
                    for pt in sg["points"]:
                        if pt["period_start"] == ps:
                            pts.append((pt["avg"], r["city"]))
                            break
            if len(pts) < 2:
                continue
            vmax = max(pts, key=lambda x: x[0])
            vmin = min(pts, key=lambda x: x[0])
            spread = vmax[0] - vmin[0]
            mid = sum(v for v, _ in pts) / len(pts)
            by_period.append({
                "period_start": ps,
                "label": ap["label"],
                "max": round(vmax[0], 2),
                "min": round(vmin[0], 2),
                "spread": round(spread, 2),
                "spread_pct": round((spread / mid) * 100, 2) if mid else 0.0,
                "max_city": vmax[1],
                "min_city": vmin[1],
                "n_cities": len(pts),
            })
        if by_period:
            spread_by_spec.append({
                "spec_key": sk,
                "spec_label": info["spec_label"],
                "align_method": info["align_method"],
                "by_period": by_period,
            })
    # 按平均 spread_pct 倒序（最"分化"的规格排前面）
    spread_by_spec.sort(key=lambda s: -(
        sum(p["spread_pct"] for p in s["by_period"]) / len(s["by_period"]) if s["by_period"] else 0
    ))

    return {
        "ok": True,
        "breed": breed,
        "cities": city_cfgs,
        "aligned_periods": aligned_periods,
        "series": series_out,
        "overall": overall,
        "spread": {
            "by_period": spread_overall_by_period,
            "by_spec": spread_by_spec,
        },
        "cross_attr_keys": cross_attr_keys,
        "top_specs": top_specs,
        "align": align,
        "unit_constraint": unit,
        "city_index_status": city_index_status,   # 各城市 NORM/DWS 选源情况（前端可提示）
    }
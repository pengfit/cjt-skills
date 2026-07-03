"""trend 页品种推荐（B+C 方案）

B 方案 `/api/stats/breed-recommend`：
  - keyword 或 l3 → 查 category_v3_rules.db 的 breed_l3_map_v3
  - JOIN category_v3 拿 name_l1/l2/l3 + gb_50500
  - 对每个品种跨城覆盖度查询（term query 多 DWS 索引并行）
  - 返回：classifications{} + breeds[] + 同 L3 计数

C 方案 `/api/stats/category-tree`：
  - 4 级分类树（前端抽屉懒加载，一次返回全量）
  - 每节点带 breed_count（该 L3 下品种数）

数据源：
  - gov-price-etl/data/category_v3_rules.db（已在 provenance.py 加载）
  - 各城市 dws_{city}_price 索引（term: breed 查覆盖度）
"""
from fastapi import APIRouter, Query
from elasticsearch import Elasticsearch
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import sys
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 复用 provenance.py 已加载的 category_v3_rules.db 路径 + ensure_schema
from api.routes.provenance import (
    _RULES_DB_CAT_V3,
    _ensure_cat_v3_tables,
    _registry_get_all,
    ES_HOST,
)

router = APIRouter()
es = Elasticsearch([ES_HOST])


# ─────────────────────────────────────────────────────────────────────────────
# B 方案：关键词推荐 + 同 L3 + 跨城覆盖度
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/stats/breed-recommend")
def breed_recommend(
    keyword: str = Query("", description="品种名关键字（LIKE 模糊匹配）"),
    l3: str = Query("", description="指定 L3 节点 code（精确）"),
    limit: int = Query(30, ge=1, le=100),
    min_confidence: float = Query(0.9, ge=0.0, le=1.0),
):
    """B 方案入口

    三种用法：
      - 只传 keyword：模糊搜 + 头部第一个 L3 作 classifications
      - 只传 l3：直接拿该 L3 下所有品种（限 limit）
      - 都传：keyword 优先，结果按 keyword 命中过滤后再按 l3 二次过滤
    """
    if not _ensure_cat_v3_tables():
        return {"ok": False, "error": "category_v3_rules.db 不可用"}

    keyword = (keyword or "").strip()
    l3 = (l3 or "").strip()

    conn = sqlite3.connect(_RULES_DB_CAT_V3)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    where = ["m.confidence >= ?"]
    params: list = [min_confidence]
    if keyword:
        where.append("m.breed_clean LIKE ?")
        params.append(f"%{keyword}%")
    if l3:
        where.append("m.l3 = ?")
        params.append(l3)
    where_sql = " AND ".join(where)

    # 关联分类法表拿 name_l1/l2/l3 + gb_50500
    c.execute(
        f"SELECT m.breed_clean, m.l3, m.source, m.confidence, "
        f"t.name_l1, t.name_l2, t.name_l3, t.gb_50500, t.unit AS default_unit "
        f"FROM breed_l3_map_v3 m "
        f"LEFT JOIN category_v3 t ON m.l3 = t.l3 "
        f"WHERE {where_sql} "
        f"ORDER BY m.confidence DESC, m.breed_clean "
        f"LIMIT ?",
        params + [limit],
    )
    rows = [dict(r) for r in c.fetchall()]

    # classifications（取第一条结果的 L3 作主分类）
    classifications = None
    if rows:
        first = rows[0]
        classifications = {
            "l1_code": first["l3"].split(".")[0] if first["l3"] else "",
            "l2_code": ".".join(first["l3"].split(".")[:2]) if first["l3"] else "",
            "l3_code": first["l3"],
            "name_l1": first["name_l1"] or "",
            "name_l2": first["name_l2"] or "",
            "name_l3": first["name_l3"] or "",
            "gb_50500": first["gb_50500"] or "",
            "default_unit": first["default_unit"] or "",
        }

    # 同 L3 总品种数（用于展示"该章节下还有 N 个品种"）
    siblings_total = 0
    if rows and rows[0]["l3"]:
        c.execute(
            "SELECT COUNT(*) AS n FROM breed_l3_map_v3 WHERE l3 = ? AND confidence >= ?",
            (rows[0]["l3"], min_confidence),
        )
        siblings_total = c.fetchone()["n"]

    conn.close()

    # ── 跨城覆盖度查询（多 DWS 索引并行） ──
    cities_with_dws = [
        {"key": s["key"], "label": s.get("label", s["key"]), "dws_index": s["dws_index"]}
        for s in _registry_get_all() if s.get("dws_index")
    ]

    def fetch_breed_cities(breed: str) -> tuple[str, list[str]]:
        """查一个品种在哪些城市 DWS 里有数据

        设计说明（2026-07-03）：
          DWS 的 breed 字段是源站原始名（“热轧带肋钢筋”）。
          breed_l3_map_v3.breed_clean 是 AI 归一化名（“HRB400E”）。
          二者经常不严格相等（ETL 未将 breed_clean 写进 DWS）。
          本接口同时报 match 与未命中原因，前端可展示
          “数据未对齐，需依赖 price-trend-compare 实时反馈”。

          后续优化：ETL 在 DWD→DWS 阶段加 breed_clean 字段后，
          改用 term 查询命中会更准。
        """
        if not cities_with_dws:
            return (breed, [])
        hits_by_city: dict[str, int] = defaultdict(int)
        for cfg in cities_with_dws:
            try:
                r = es.count(
                    index=cfg["dws_index"],
                    body={"query": {"match": {"breed": breed}}},
                    ignore_unavailable=True,
                    allow_no_indices=True,
                )
                if r.get("count", 0) > 0:
                    hits_by_city[cfg["key"]] = r["count"]
            except Exception:
                continue
        sorted_keys = sorted(hits_by_city.keys(), key=lambda k: -hits_by_city[k])
        return (breed, sorted_keys[:6])

    coverages: dict[str, list[str]] = {}
    if rows:
        with ThreadPoolExecutor(max_workers=min(len(rows), 8)) as pool:
            futures = {pool.submit(fetch_breed_cities, r["breed_clean"]): r["breed_clean"] for r in rows}
            for f in as_completed(futures):
                breed, cities = f.result()
                coverages[breed] = cities

    # 组装结果
    breeds_out = []
    for r in rows:
        cities = coverages.get(r["breed_clean"], [])
        breeds_out.append({
            "breed_clean": r["breed_clean"],
            "l3": r["l3"],
            "name_l3": r["name_l3"],
            "source": r["source"],
            "confidence": r["confidence"],
            "gb_50500": r["gb_50500"] or "",
            "city_count": len(cities),
            "cities": cities,  # 最多 6 个城市 key
        })

    return {
        "ok": True,
        "query": {"keyword": keyword, "l3": l3, "limit": limit, "min_confidence": min_confidence},
        "classifications": classifications,
        "siblings_total": siblings_total,
        "breeds": breeds_out,
        "dws_cities_total": len(cities_with_dws),  # 用于前端显示 "N/总数 城市"
        "coverage_note": (
            "当前 DWS.breed 与 breed_l3_map_v3.breed_clean 未对齐；"
            "city_count 字段仅供参考，实际跨城数据以 /api/stats/price-trend-compare 返回为准。"
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# C 方案：4 级分类树（一次返回全量，每节点带 breed_count）
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/api/stats/category-tree")
def category_tree(min_confidence: float = Query(0.9, ge=0.0, le=1.0)):
    """C 方案入口：返回 4 级分类树，每 L3 节点带该分类下的品种数

    数据量级：191 个分类节点 + 9077 行品种映射，单次返回 JSON < 200 KB。
    """
    if not _ensure_cat_v3_tables():
        return {"ok": False, "error": "category_v3_rules.db 不可用"}

    conn = sqlite3.connect(_RULES_DB_CAT_V3)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 1. 全部分类节点
    c.execute(
        "SELECT l1, l2, l3, l4, gb_50500, name_l1, name_l2, name_l3, name_l4 "
        "FROM category_v3 ORDER BY l1, l2, l3, l4"
    )
    nodes = [dict(r) for r in c.fetchall()]

    # 2. 每个 L3 的品种数（仅 confidence ≥ 阈值）
    c.execute(
        "SELECT l3, COUNT(*) AS n FROM breed_l3_map_v3 "
        "WHERE confidence >= ? GROUP BY l3",
        (min_confidence,),
    )
    breed_count_by_l3 = {r["l3"]: r["n"] for r in c.fetchall()}

    conn.close()

    # 3. 装配 4 级树（l1 → l2 → l3 → l4）
    tree: dict = {}
    for n in nodes:
        l1 = tree.setdefault(n["l1"], {
            "code": n["l1"], "name": n["name_l1"],
            "l2_list": {}, "l2_count": 0, "l3_count": 0, "breed_count": 0,
        })
        l2 = l1["l2_list"].setdefault(n["l2"], {
            "code": n["l2"], "name": n["name_l2"], "l1_code": n["l1"],
            "l3_list": {}, "l3_count": 0, "breed_count": 0,
        })
        l3 = l2["l3_list"].setdefault(n["l3"], {
            "code": n["l3"], "name": n["name_l3"], "l1_code": n["l1"], "l2_code": n["l2"],
            "gb_50500": n["gb_50500"],
            "l4_list": [], "breed_count": breed_count_by_l3.get(n["l3"], 0),
        })
        if n["l4"] and n["l4"] != "UNCLASSIFIED":
            l3["l4_list"].append({"code": n["l4"], "name": n["name_l4"]})

    # 4. 转 list + 自下而上聚合 breed_count
    out_l1 = []
    for l1_code, l1 in tree.items():
        out_l2 = []
        for l2_code, l2 in l1["l2_list"].items():
            out_l3 = []
            for l3_code, l3 in l2["l3_list"].items():
                out_l3.append(l3)
                l2["breed_count"] += l3["breed_count"]
            l2["l3_list"] = out_l3
            l2["l3_count"] = len(out_l3)
            out_l2.append(l2)
            l1["breed_count"] += l2["breed_count"]
        l1["l2_list"] = out_l2
        l1["l2_count"] = len(out_l2)
        l1["l3_count"] = sum(l2["l3_count"] for l2 in out_l2)
        out_l1.append(l1)
    out_l1.sort(key=lambda x: x["code"])

    return {
        "ok": True,
        "min_confidence": min_confidence,
        "l1_count": len(out_l1),
        "l2_count": sum(l["l2_count"] for l in out_l1),
        "l3_count": sum(l["l3_count"] for l in out_l1),
        "breed_total": sum(l["breed_count"] for l in out_l1),
        "tree": out_l1,
    }
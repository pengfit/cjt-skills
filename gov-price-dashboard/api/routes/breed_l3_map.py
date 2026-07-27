"""breed_l3_map.py — 数据治理 · 分类映射后台 (breed_l3_map_v3 表)

数据源：data/category_v3_rules.db · 表 breed_l3_map_v3
字段：breed_clean / l3 / source / confidence / created_at / updated_at

端点：
  GET /api/stats/breed-l3-map/stats    总览（总数 / distinct breeds / source 分布 / L3 top10）
  GET /api/stats/breed-l3-map         分页 + 搜索 + 过滤（l3 / source / min_confidence）
  GET /api/stats/breed-l3-map/{breed} 单条详情

设计：
  - 与 canon.py 同款：query_only=ON 防误写
  - 与 provenance.py 同款：_v2_conn row_factory=sqlite3.Row
  - 与 search.py 同款：分页 page=1&size=20,上限 size=200
  - 搜索：breed_clean 模糊匹配（%X%）
  - 过滤：source / l3 精确匹配；min_confidence 阈值
  - 排序：updated_at DESC（最新改动在前）
"""
from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from api.paths import CATEGORY_V3_RULES_DB

router = APIRouter(prefix="/api/stats/breed-l3-map", tags=["breed-l3-map"])


def _connect_readonly() -> sqlite3.Connection:
    """只读连接 — 与现有 modules 一致,query_only 防误写"""
    con = sqlite3.connect(f"file:{CATEGORY_V3_RULES_DB}?mode=ro", uri=True, timeout=30)
    con.execute("PRAGMA query_only=ON")
    con.row_factory = sqlite3.Row
    return con


def _check_ready() -> Optional[dict]:
    """DB 不存在或表缺失时返错误 dict,否则 None"""
    if not CATEGORY_V3_RULES_DB.exists():
        return {"ok": False, "error": f"DB 不存在: {CATEGORY_V3_RULES_DB}"}
    try:
        con = _connect_readonly()
        names = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        con.close()
        if "breed_l3_map_v3" not in names:
            return {"ok": False, "error": "breed_l3_map_v3 表不存在"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return None


def _row_to_dict(r) -> dict:
    return {
        "breed_clean": r["breed_clean"],
        "l3": r["l3"] or "",
        "source": r["source"] or "",
        "confidence": float(r["confidence"]) if r["confidence"] is not None else 0.0,
        "created_at": r["created_at"] or "",
        "updated_at": r["updated_at"] or "",
    }


@router.get("/stats")
def breed_l3_map_stats():
    """总览：总数 / distinct breeds / source 分布 / L3 top10"""
    err = _check_ready()
    if err:
        return err

    con = _connect_readonly()
    try:
        total = con.execute("SELECT COUNT(*) FROM breed_l3_map_v3").fetchone()[0]
        distinct_breed = con.execute(
            "SELECT COUNT(DISTINCT breed_clean) FROM breed_l3_map_v3"
        ).fetchone()[0]
        distinct_l3 = con.execute(
            "SELECT COUNT(DISTINCT l3) FROM breed_l3_map_v3 WHERE l3 IS NOT NULL AND l3 != ''"
        ).fetchone()[0]
        null_l3 = con.execute(
            "SELECT COUNT(*) FROM breed_l3_map_v3 "
            "WHERE l3 IS NULL OR l3 = ''"
        ).fetchone()[0]

        # source 分布
        by_source = dict(con.execute(
            "SELECT source, COUNT(*) FROM breed_l3_map_v3 "
            "GROUP BY source ORDER BY 2 DESC"
        ).fetchall())

        # L3 top10
        top10_l3 = dict(con.execute(
            "SELECT COALESCE(l3, 'UNCLASSIFIED'), COUNT(*) "
            "FROM breed_l3_map_v3 GROUP BY l3 ORDER BY 2 DESC LIMIT 10"
        ).fetchall())

        # confidence 分布
        conf_buckets = {
            "0.95+": con.execute(
                "SELECT COUNT(*) FROM breed_l3_map_v3 WHERE confidence >= 0.95"
            ).fetchone()[0],
            "0.85-0.95": con.execute(
                "SELECT COUNT(*) FROM breed_l3_map_v3 "
                "WHERE confidence >= 0.85 AND confidence < 0.95"
            ).fetchone()[0],
            "0.50-0.85": con.execute(
                "SELECT COUNT(*) FROM breed_l3_map_v3 "
                "WHERE confidence >= 0.5 AND confidence < 0.85"
            ).fetchone()[0],
            "<0.50": con.execute(
                "SELECT COUNT(*) FROM breed_l3_map_v3 WHERE confidence < 0.5"
            ).fetchone()[0],
        }

        return {
            "ok": True,
            "db_path": str(CATEGORY_V3_RULES_DB),
            "total_mappings": total,
            "distinct_breed": distinct_breed,
            "distinct_l3": distinct_l3,
            "null_l3": null_l3,
            "by_source": by_source,
            "top10_l3": top10_l3,
            "confidence_buckets": conf_buckets,
        }
    finally:
        con.close()


@router.get("")
def breed_l3_map_list(
    page: int = Query(1, ge=1, le=10000, description="页码(从 1 开始)"),
    size: int = Query(20, ge=1, le=200, description="每页条数(上限 200)"),
    search: Optional[str] = Query(None, description="模糊搜索 breed_clean"),
    source: Optional[str] = Query(None, description="按 source 精确过滤"),
    l3: Optional[str] = Query(None, description="按 l3 精确过滤"),
    min_confidence: Optional[float] = Query(None, ge=0.0, le=1.0, description="confidence 阈值"),
    sort_by: str = Query("updated_at", description="排序字段:updated_at / confidence / breed_clean"),
    order: str = Query("desc", description="排序方向:asc / desc"),
):
    """分页查 breed_l3_map_v3,带搜索 + 过滤

    返回: {rows: [...], total: N, page, size, sources: [...], l3_codes: [...]}
    """
    err = _check_ready()
    if err:
        return {"rows": [], "total": 0, "page": 1, "size": 20, "sources": [], "l3_codes": [], **err}

    offset = (page - 1) * size
    sort_col = {
        "updated_at": "updated_at",
        "confidence": "confidence",
        "breed_clean": "breed_clean",
    }.get(sort_by, "updated_at")
    sort_dir = "DESC" if order.lower() == "desc" else "ASC"

    where = []
    params = []
    if search:
        where.append("breed_clean LIKE ?")
        params.append(f"%{search}%")
    if source:
        where.append("source = ?")
        params.append(source)
    if l3:
        where.append("l3 = ?")
        params.append(l3)
    if min_confidence is not None:
        where.append("confidence >= ?")
        params.append(min_confidence)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    con = _connect_readonly()
    try:
        # total
        total = con.execute(
            f"SELECT COUNT(*) FROM breed_l3_map_v3 {where_sql}", params
        ).fetchone()[0]

        # rows
        rows = con.execute(
            f"SELECT breed_clean, l3, source, confidence, created_at, updated_at "
            f"FROM breed_l3_map_v3 {where_sql} "
            f"ORDER BY {sort_col} {sort_dir}, breed_clean DESC "
            f"LIMIT ? OFFSET ?",
            [*params, size, offset],
        ).fetchall()

        # distinct sources / l3_codes (供前端下拉)
        sources = [r[0] for r in con.execute(
            "SELECT DISTINCT source FROM breed_l3_map_v3 "
            "WHERE source IS NOT NULL AND source != '' "
            "ORDER BY source"
        ).fetchall()]
        l3_codes = [r[0] for r in con.execute(
            "SELECT DISTINCT l3 FROM breed_l3_map_v3 "
            "WHERE l3 IS NOT NULL AND l3 != '' "
            "ORDER BY l3"
        ).fetchall()]

        return {
            "rows": [_row_to_dict(r) for r in rows],
            "total": total,
            "page": page,
            "size": size,
            "sources": sources,
            "l3_codes": l3_codes,
            "sort": sort_by,
            "order": order,
        }
    finally:
        con.close()


@router.get("/{breed_clean}")
def breed_l3_map_detail(breed_clean: str):
    """单条详情"""
    err = _check_ready()
    if err:
        raise HTTPException(503, err["error"])

    con = _connect_readonly()
    try:
        row = con.execute(
            "SELECT breed_clean, l3, source, confidence, created_at, updated_at "
            "FROM breed_l3_map_v3 WHERE breed_clean = ?",
            (breed_clean,),
        ).fetchone()
        if not row:
            raise HTTPException(404, f"breed_clean not found: {breed_clean}")
        return _row_to_dict(row)
    finally:
        con.close()
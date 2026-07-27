"""canon.py — 后台数据治理 · 品种归一 (breed_canonical) 管理端点

提供:
  - GET /api/canon/breeds          分页 + 搜索 + 筛选 (breed_clean / normalized_breed / l3_code / source)
  - GET /api/canon/breeds/stats    总览(总数 / distinct / by source / by l3 / reject 数)
  - GET /api/canon/breeds/<breed> 单条详情(含 note / created_at / updated_at)

设计:
  - 复用 gov_price_normalization.data.breed_canonical.get_stats() 做总览
  - 自己起 read-only sqlite3 连接(只读 + WAL + query_only)防误写
  - 分页:page=1&size=20,上限 size=200
  - 搜索:breed_clean / normalized_breed 模糊匹配(%X%)
  - 筛选:source / l3_code 精确匹配;null_l3=true 查 l3_code IS NULL OR ''
  - 排序:updated_at DESC(最新改动在前)
"""
from __future__ import annotations
import sys
import os
import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

# 从 routes/ 上去 4 层 = skills/(routes → api → gov-price-dashboard → skills)
_SKILLS = Path(__file__).resolve().parent.parent.parent.parent
_PKG = _SKILLS / "gov-price-normalization"
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from gov_price_normalization.data.breed_canonical import DB_PATH  # noqa: E402

router = APIRouter(prefix="/api/canon", tags=["canon"])


def _connect_readonly() -> sqlite3.Connection:
    """只读连接 — 跟现有 modules 一致,query_only 防误写"""
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=30)
    con.execute("PRAGMA query_only=ON")
    con.row_factory = sqlite3.Row
    return con


def _row_to_dict(r) -> dict:
    return {
        "breed_clean": r["breed_clean"],
        "normalized_breed": r["normalized_breed"],
        "l3_code": r["l3_code"] or "",
        "confidence": float(r["confidence"]) if r["confidence"] is not None else 0.0,
        "source": r["source"] or "",
        "note": r["note"] or "",
        "created_at": r["created_at"] or "",
        "updated_at": r["updated_at"] or "",
    }


@router.get("/breeds/stats")
def canon_breeds_stats():
    """总览:总数 / distinct / by source / top 10 l3 / reject 数 / 最近一次 run"""
    con = _connect_readonly()
    try:
        total = con.execute("SELECT COUNT(*) FROM breed_canonical").fetchone()[0]
        distinct_norm = con.execute(
            "SELECT COUNT(DISTINCT normalized_breed) FROM breed_canonical"
        ).fetchone()[0]
        by_source = dict(con.execute(
            "SELECT source, COUNT(*) FROM breed_canonical "
            "GROUP BY source ORDER BY 2 DESC"
        ).fetchall())
        top10_l3 = dict(con.execute(
            "SELECT COALESCE(l3_code, 'UNCLASSIFIED'), COUNT(*) "
            "FROM breed_canonical GROUP BY l3_code ORDER BY 2 DESC LIMIT 10"
        ).fetchall())
        null_l3 = con.execute(
            "SELECT COUNT(*) FROM breed_canonical "
            "WHERE l3_code IS NULL OR l3_code = ''"
        ).fetchone()[0]
        reject_count = con.execute(
            "SELECT COUNT(*) FROM canonical_reject"
        ).fetchone()[0]
        # 最近一次 run
        last_run_row = con.execute(
            "SELECT event, input_count, new_count, failed_count, "
            "duration_sec, created_at FROM canonical_run ORDER BY id DESC LIMIT 1"
        ).fetchone()
        last_run = dict(last_run_row) if last_run_row else None
        # confidence 分布
        conf_buckets = {
            "0.95+": con.execute(
                "SELECT COUNT(*) FROM breed_canonical WHERE confidence >= 0.95"
            ).fetchone()[0],
            "0.85-0.95": con.execute(
                "SELECT COUNT(*) FROM breed_canonical "
                "WHERE confidence >= 0.85 AND confidence < 0.95"
            ).fetchone()[0],
            "0.50-0.85": con.execute(
                "SELECT COUNT(*) FROM breed_canonical "
                "WHERE confidence >= 0.5 AND confidence < 0.85"
            ).fetchone()[0],
            "<0.50": con.execute(
                "SELECT COUNT(*) FROM breed_canonical WHERE confidence < 0.5"
            ).fetchone()[0],
        }
        return {
            "db_path": str(DB_PATH),
            "total_mappings": total,
            "distinct_normalized_breed": distinct_norm,
            "merge_ratio": round(distinct_norm / total, 4) if total else 0,
            "null_l3": null_l3,
            "reject_count": reject_count,
            "by_source": by_source,
            "top10_l3": top10_l3,
            "confidence_buckets": conf_buckets,
            "last_run": last_run,
        }
    finally:
        con.close()


@router.get("/breeds")
def canon_breeds(
    page: int = Query(1, ge=1, le=10000, description="页码(从 1 开始)"),
    size: int = Query(20, ge=1, le=200, description="每页条数(上限 200)"),
    search: Optional[str] = Query(None, description="模糊搜索 breed_clean / normalized_breed"),
    source: Optional[str] = Query(None, description="按 source 精确过滤"),
    l3_code: Optional[str] = Query(None, description="按 l3_code 精确过滤"),
    null_l3: bool = Query(False, description="只看 l3_code 为空的记录"),
    sort: str = Query("updated_at", description="排序字段:updated_at / confidence / breed_clean"),
    order: str = Query("desc", description="排序方向:asc / desc"),
):
    """分页查 breed_canonical,带搜索 + 过滤

    返回: {rows: [...], total: N, page, size, sources: [...], l3_codes: [...]}
    """
    offset = (page - 1) * size
    # 白名单 sort / order 防 SQL 注入
    sort_col = {
        "updated_at": "updated_at",
        "confidence": "confidence",
        "breed_clean": "breed_clean",
        "normalized_breed": "normalized_breed",
    }.get(sort, "updated_at")
    sort_dir = "DESC" if order.lower() == "desc" else "ASC"

    where = []
    params = []
    if search:
        where.append("(breed_clean LIKE ? OR normalized_breed LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like])
    if source:
        where.append("source = ?")
        params.append(source)
    if l3_code:
        where.append("l3_code = ?")
        params.append(l3_code)
    if null_l3:
        where.append("(l3_code IS NULL OR l3_code = '')")

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    con = _connect_readonly()
    try:
        # total
        total = con.execute(
            f"SELECT COUNT(*) FROM breed_canonical {where_sql}", params
        ).fetchone()[0]
        # rows
        rows = con.execute(
            f"SELECT breed_clean, normalized_breed, l3_code, confidence, "
            f"source, note, created_at, updated_at "
            f"FROM breed_canonical {where_sql} "
            # 2026-07-27:secondary sort 用 breed_clean DESC(breed_canonical 表没 id 列)
            f"ORDER BY {sort_col} {sort_dir}, breed_clean DESC "
            f"LIMIT ? OFFSET ?",
            [*params, size, offset],
        ).fetchall()
        # distinct sources / l3_codes (供前端下拉)
        sources = [r[0] for r in con.execute(
            "SELECT DISTINCT source FROM breed_canonical "
            "WHERE source IS NOT NULL AND source != '' "
            "ORDER BY source"
        ).fetchall()]
        l3_codes = [r[0] for r in con.execute(
            "SELECT DISTINCT l3_code FROM breed_canonical "
            "WHERE l3_code IS NOT NULL AND l3_code != '' "
            "ORDER BY l3_code"
        ).fetchall()]
        return {
            "rows": [_row_to_dict(r) for r in rows],
            "total": total,
            "page": page,
            "size": size,
            "sources": sources,
            "l3_codes": l3_codes,
            "sort": sort,
            "order": order,
        }
    finally:
        con.close()


@router.get("/breeds/{breed_clean}")
def canon_breed_detail(breed_clean: str):
    """单条详情"""
    con = _connect_readonly()
    try:
        row = con.execute(
            "SELECT breed_clean, normalized_breed, l3_code, confidence, "
            "source, note, created_at, updated_at "
            "FROM breed_canonical WHERE breed_clean = ?",
            (breed_clean,),
        ).fetchone()
        if not row:
            raise HTTPException(404, f"breed_clean not found: {breed_clean}")
        return _row_to_dict(row)
    finally:
        con.close()

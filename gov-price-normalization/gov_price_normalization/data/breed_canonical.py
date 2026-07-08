"""breed_canonical DB 访问层

DB 位置：~/.openclaw/workspace/cjt/skills/data/breed_canonical.db
  - 共享数据目录（跨包：gov-price-etl 写、gov-price-normalization 读、未来 dashboard 可读）
  - 详见 SKILL.md Phase A+

表：
  - breed_canonical : breed_clean → normalized_breed (主表)
  - canonical_run   : 累积审计（bootstrap / batch_resolve / rebuild_norm）
  - canonical_reject: AI 解析失败 / 拒绝入库的 breed_clean

设计要点：
  - 进程内缓存：全量加载一次（10K+ 行），二次查询 O(1)
  - WAL 模式：读进程（build_norm_index.py）不阻塞写进程（canonicalize_breeds.py）
  - query_only=ON：读连接不能写，防误操作
  - 缓存失效：clear_cache() 后下次重新从 DB 拉

用法：
    from gov_price_normalization.data.breed_canonical import get_canonical, get_canonical_batch

    hit = get_canonical("热轧光圆钢筋（高线）")
    # → {"normalized_breed": "...", "l3_code": "01.01.01", "confidence": 0.95, "source": "etl_v3_sqlite"}
    # → None if not in map

    batch = get_canonical_batch(["A", "B", "C"])
    # → {"A": {...}, "B": {...}, "C": None}
"""
from __future__ import annotations
import os
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Optional

# ── DB 路径解析 ────────────────────────────────────────────────────────
# 优先级：
#   1. 环境变量 BREED_CANONICAL_DB
#   2. <skills>/data/breed_canonical.db（共享目录，独立于 etl 的 category_v3_rules.db，后者在 gov-price-etl/data/）
#   3. 兼容旧路径：<pkg>/data/breed_canonical.db（早期开发版）
#
# 路径反推：
#   <pkg>/gov_price_normalization/data/breed_canonical.py
#   → .parent = data/  → .parent.parent = gov_price_normalization/
#   → .parent.parent.parent = gov-price-normalization/
#   → .parent.parent.parent.parent = skills/
_HERE = Path(__file__).resolve()
_PKG = _HERE.parent.parent          # gov_price_normalization/
_SKILL = _PKG.parent                # gov-price-normalization/
_SKILLS = _SKILL.parent             # skills/
_SHARED_DB = _SKILLS / "data" / "breed_canonical.db"
_LEGACY_DB = _PKG / "data" / "breed_canonical.db"


def _resolve_db_path() -> Path:
    env = os.environ.get("BREED_CANONICAL_DB")
    if env:
        return Path(env).expanduser()
    if _SHARED_DB.exists():
        return _SHARED_DB
    if _LEGACY_DB.exists():
        return _LEGACY_DB
    # 默认走共享目录（即使还没建，writer 端会建）
    return _SHARED_DB


DB_PATH = _resolve_db_path()


# ── 缓存 ──────────────────────────────────────────────────────────────
_cache: Optional[dict] = None
_lock = RLock()


def _connect_readonly() -> sqlite3.Connection:
    """只读连接 + WAL + query_only"""
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=30)
    con.execute("PRAGMA query_only=ON")
    con.row_factory = sqlite3.Row
    return con


def _load_full_map() -> dict:
    """全量加载主表到内存 dict（进程内缓存）"""
    con = _connect_readonly()
    try:
        cur = con.execute(
            "SELECT breed_clean, normalized_breed, l3_code, confidence, source "
            "FROM breed_canonical"
        )
        return {
            row["breed_clean"]: {
                "normalized_breed": row["normalized_breed"],
                "l3_code": row["l3_code"],
                "confidence": float(row["confidence"]) if row["confidence"] is not None else 0.0,
                "source": row["source"],
            }
            for row in cur.fetchall()
        }
    finally:
        con.close()


def get_canonical(breed_clean: str) -> Optional[dict]:
    """单条查询：breed_clean → {normalized_breed, l3_code, confidence, source}

    Returns:
        None if not in map（调用方应走 raw fallback）
    """
    if not breed_clean:
        return None
    global _cache
    with _lock:
        if _cache is None:
            _cache = _load_full_map()
        return _cache.get(breed_clean)


def get_canonical_batch(breed_cleans: list) -> dict:
    """批量查询，返回 {breed_clean: row or None}"""
    global _cache
    with _lock:
        if _cache is None:
            _cache = _load_full_map()
        return {bc: _cache.get(bc) for bc in breed_cleans if bc}


def get_stats() -> dict:
    """汇总统计：总条数 / distinct / by source / by l3"""
    con = _connect_readonly()
    try:
        total = con.execute("SELECT COUNT(*) FROM breed_canonical").fetchone()[0]
        distinct_norm = con.execute(
            "SELECT COUNT(DISTINCT normalized_breed) FROM breed_canonical"
        ).fetchone()[0]
        by_source = dict(con.execute(
            "SELECT source, COUNT(*) FROM breed_canonical GROUP BY source ORDER BY 2 DESC"
        ).fetchall())
        by_l3 = dict(con.execute(
            "SELECT COALESCE(l3_code, 'UNCLASSIFIED'), COUNT(*) "
            "FROM breed_canonical GROUP BY l3_code ORDER BY 2 DESC LIMIT 10"
        ).fetchall())
        last_run = con.execute(
            "SELECT event, input_count, new_count, duration_sec, created_at "
            "FROM canonical_run ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return {
            "db_path": str(DB_PATH),
            "total_mappings": total,
            "distinct_normalized_breed": distinct_norm,
            "merge_ratio": round(distinct_norm / total, 4) if total else 0,
            "by_source": by_source,
            "top10_l3": by_l3,
            "last_run": dict(last_run) if last_run else None,
        }
    finally:
        con.close()


def clear_cache() -> None:
    """清缓存。DB 内容被外部更新后调一次（重建 NORM 前/后）"""
    global _cache
    with _lock:
        _cache = None


def has_cache() -> bool:
    """是否已加载缓存（debug 用）"""
    return _cache is not None


__all__ = [
    "DB_PATH",
    "get_canonical",
    "get_canonical_batch",
    "get_stats",
    "clear_cache",
    "has_cache",
]

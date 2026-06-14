"""ai_cache.py - AI 调用结果持久化缓存

设计目标：
  - 重复 spec 文本不再重复送 AI（命中率应 >50%）
  - 进程内 dict（_ai_cache）+ 进程间 SQLite（ai_cache.db）双层
  - 缓存 key = SHA1(spec + breed + category) 避免重复
  - 缓存 value = JSON 序列化的 AI 响应

位置：与 etl.py 同目录（运行时数据，不进 git）
"""

import hashlib
import json
import os
import sqlite3
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "ai_cache.db")


def _connect():
    """Open SQLite connection with WAL mode (allow concurrent readers)."""
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_table():
    """Create ai_cache table if not exists (idempotent)."""
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_cache (
            cache_key TEXT PRIMARY KEY,
            value     TEXT NOT NULL,
            hit_count INTEGER DEFAULT 0,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_cache_updated ON ai_cache(updated_at)")
    conn.close()


# 进程内 LRU 缓存（避免每次都查 SQLite）
_memory_cache: dict[str, dict] = {}
_loaded = False


def _load_memory_cache():
    """进程启动时把 SQLite 热点数据加载到内存（只加载最近 7 天的 5000 条）。"""
    global _loaded
    if _loaded:
        return
    _ensure_table()
    conn = _connect()
    rows = conn.execute(
        "SELECT cache_key, value FROM ai_cache "
        "WHERE updated_at > datetime('now', '-7 days') "
        "ORDER BY hit_count DESC LIMIT 5000"
    ).fetchall()
    for r in rows:
        try:
            _memory_cache[r["cache_key"]] = json.loads(r["value"])
        except Exception:
            pass
    _loaded = True
    conn.close()


def make_key(kind: str, *parts: str) -> str:
    """Build cache key from kind + parts (spec, breed, category, etc.)"""
    h = hashlib.sha1()
    h.update(kind.encode("utf-8"))
    for p in parts:
        h.update(b"|")
        h.update(p.encode("utf-8"))
    return h.hexdigest()


def get(kind: str, *parts: str):
    """Get cached AI result. Returns parsed dict or None."""
    _load_memory_cache()
    key = make_key(kind, *parts)
    if key in _memory_cache:
        return _memory_cache[key]
    # 内存未命中，查 SQLite
    _ensure_table()
    conn = _connect()
    row = conn.execute(
        "SELECT value FROM ai_cache WHERE cache_key = ?", (key,)
    ).fetchone()
    conn.close()
    if row:
        try:
            val = json.loads(row["value"])
            _memory_cache[key] = val
            return val
        except Exception:
            return None
    return None


def put(kind: str, value, *parts: str) -> str:
    """Persist AI result to memory + SQLite. Returns cache key."""
    _load_memory_cache()
    key = make_key(kind, *parts)
    _memory_cache[key] = value
    _ensure_table()
    conn = _connect()
    conn.execute(
        "INSERT OR REPLACE INTO ai_cache (cache_key, value, hit_count, updated_at) "
        "VALUES (?, ?, COALESCE((SELECT hit_count FROM ai_cache WHERE cache_key = ?), 0) + 1, ?)",
        (key, json.dumps(value, ensure_ascii=False), key, time.strftime("%Y-%m-%dT%H:%M:%S")),
    )
    conn.close()
    return key


def stats() -> dict:
    """Cache statistics for health reports."""
    _ensure_table()
    conn = _connect()
    total = conn.execute("SELECT COUNT(*) AS c FROM ai_cache").fetchone()["c"]
    by_kind = conn.execute(
        "SELECT substr(cache_key, 1, 1) AS k, COUNT(*) AS c FROM ai_cache GROUP BY k"
    ).fetchall()
    conn.close()
    return {
        "total_entries": total,
        "memory_size": len(_memory_cache),
        "by_kind": {r["k"]: r["c"] for r in by_kind},
    }


if __name__ == "__main__":
    print(json.dumps(stats(), ensure_ascii=False, indent=2))

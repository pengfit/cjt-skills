"""classify/rules/_core.py - v1 品种分类（仅 DB 查表路径）

ODS → DWD 阶段保留的 v1 路径（无 AI），用于：
  1. 兼容旧 ETL pipeline 的 category 字段输出
  2. spec 规则库（breed_spec_rules.db）按 v1 category 过滤

v1 阶段 3 AI 串行已删除（2026-06-16 清理 v1/v2 合并）：
  - 大分类任务已并入 v2 4 层分类（classify/category_v2.py → classify_v2_batch）
  - 兜底逻辑由 v2 的 stage5_unit_fallback 接管
  - v1 AI prompt（classify_breed_batch）从 prompts.yml 删除

公开 API（v1 仅保留 DB 查表路径）：
  classify_breed_db_exact(breed)      → (category, 'db_exact' | '')
  classify_breed_db_fuzzy(breed)      → (category, 'db_fuzzy' | '')
  classify_breed_local(breed)         → (category, 'db_exact'|'db_fuzzy'|'')   阶段 1+2
  classify_breed(breed, ...)          → category 字符串（DB 未命中返回 '其他'）

约定 source 取值（仅 v1 DB 阶段）：
  'db_exact'    阶段 1 命中（DB 精确查表）
  'db_fuzzy'    阶段 2 命中（DB 模糊召回 / Jaccard）
  ''            阶段 1+2 都未命中（v1 不再调 AI，classify_breed 返回 '其他'）
"""
from typing import Tuple
import sqlite3
import threading

from gov_price_etl.paths import CATEGORY_RULES_DB

# ── 进程级独立连接（连 breed_category_rules.db，与 vec_store 隔离） ──────
_DB_CONN: sqlite3.Connection | None = None
_DB_LOCK = threading.Lock()

def _get_category_db_conn() -> sqlite3.Connection:
    """独立维护 breed_category_rules.db 的连接，避免与 vec_store 串扰。"""
    global _DB_CONN
    if _DB_CONN is None:
        with _DB_LOCK:
            if _DB_CONN is None:
                _DB_CONN = sqlite3.connect(
                    str(CATEGORY_RULES_DB), check_same_thread=False, timeout=30
                )
                _DB_CONN.execute("PRAGMA journal_mode=WAL")
    return _DB_CONN

# 向后兼容：保留旧名
def _get_db_conn() -> sqlite3.Connection:
    return _get_category_db_conn()

# ── 阶段 1: 本地库精确匹配 ────────────────────────────────────────────────
def classify_breed_db_exact(breed: str) -> Tuple[str, str]:
    """阶段 1：直接查 breed_category_rules.db。

    Args:
        breed: 清洗后的品种名（breed_clean）

    Returns:
        (category, source)
        - 命中: (category, 'db_exact')
        - 未命中: ('', '')
    """
    if not breed:
        return ("", "")
    try:
        conn = _get_category_db_conn()
        row = conn.execute(
            "SELECT category FROM breed_category_rules WHERE breed = ? LIMIT 1",
            (breed.strip(),),
        ).fetchone()
        if row and row[0]:
            return (row[0], "db_exact")
    except Exception:
        pass
    return ("", "")

# ── 阶段 2: 本地库模糊召回（Jaccard + 倒排） ─────────────────────────────
def classify_breed_db_fuzzy(breed: str, threshold: float = 0.45) -> Tuple[str, str]:
    """阶段 2：Jaccard 相似度召回（查 DB + 文本规则）。

    Args:
        breed:     清洗后的品种名
        threshold: Jaccard 阈值（默认 0.45）

    Returns:
        (category, source)
        - 命中: (category, 'db_fuzzy')
        - 未命中: ('', '')
    """
    if not breed:
        return ("", "")
    try:
        from gov_price_etl.classify.rules.jaccard import jaccard_breed_classify
        cat, score = jaccard_breed_classify(breed.strip(), threshold=threshold)
        if cat and score >= threshold:
            return (cat, "db_fuzzy")
    except Exception:
        pass
    return ("", "")


# ── 阶段 1+2 合并：本地规则库匹配 ────────────────────────────────────────
def classify_breed_local(breed: str, threshold: float = 0.45) -> Tuple[str, str]:
    """阶段 1+2：先 DB 精确查表，再 DB 模糊召回。

    Returns:
        (category, source)
        - 阶段 1 命中: (category, 'db_exact')
        - 阶段 2 命中: (category, 'db_fuzzy')
        - 都未命中: ('', '')
    """
    cat, src = classify_breed_db_exact(breed)
    if cat:
        return (cat, src)
    return classify_breed_db_fuzzy(breed, threshold=threshold)


def classify_breed(breed: str, spec: str = "", city: str = "") -> str:
    """兼容旧接口：返回 category 字符串（纯 DB 查表，不调 AI）。

    流程：
      1. 本地 DB 精确匹配
      2. 本地 DB 模糊召回
      3. 未命中 → 返回 "其他"

    v1 AI 分类已删除（2026-06-16），全部分类由 v2 4 层接管。
    """
    cat, _src = classify_breed_local(breed)
    return cat or "其他"

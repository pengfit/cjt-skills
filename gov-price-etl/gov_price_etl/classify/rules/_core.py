"""classify/rules/_core.py - 品种分类三段式（明确节点）

ODS → DWD 阶段的品种分类流程，每个阶段返回 (category, source)：

  ┌─────────────────────────────────────────────────────────────────────┐
  │ 阶段 1: 本地库精确匹配  (breed_category_rules.db)                    │
  │   - 直接 SQL `WHERE breed = ?`                                       │
  │   - 命中即返回 source='db_exact'                                     │
  │   - 未命中 → 进入阶段 2                                              │
  ├─────────────────────────────────────────────────────────────────────┤
  │ 阶段 2: 本地库模糊召回  (DB + Jaccard)                               │
  │   - DB 里所有规则预先分词建倒排索引                                   │
  │   - 倒排精确包含 / Dice + 加权 Jaccard (阈值 0.45)                    │
  │   - 命中即返回 source='db_fuzzy'                                     │
  │   - 未命中 → 进入阶段 3                                              │
  ├─────────────────────────────────────────────────────────────────────┤
  │ 阶段 3: AI 串行分类   (classify_breed_batch)                         │
  │   - 批量送 AI（默认 20 条/批）                                       │
  │   - 失败兜底 "其他"                                                  │
  │   - 命中返回 source='ai'                                             │
  │   - 兜底返回 source='ai_fallback'                                    │
  └─────────────────────────────────────────────────────────────────────┘

公开 API：
  classify_breed_db_exact(breed)      → (category, 'db_exact' | '')
  classify_breed_db_fuzzy(breed)      → (category, 'db_fuzzy' | '')
  classify_breed_local(breed)         → (category, 'db_exact'|'db_fuzzy'|'')   阶段 1+2
  classify_breed_ai(breed, city)      → (category, 'ai' | 'ai_fallback')      阶段 3
  classify_breed(breed, ...)          → (category, source)                    三段合并（兼容旧接口）

约定 source 取值：
  'db_exact'    阶段 1 命中（DB 精确查表）
  'db_fuzzy'    阶段 2 命中（DB 模糊召回 / Jaccard）
  'ai'          阶段 3 命中（AI 分类成功）
  'ai_fallback' 阶段 3 兜底（AI 失败 → "其他"）
  ''            阶段 1+2 都未命中（AI 阶段尚未触发）
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


# ── 阶段 3: AI 串行分类 ─────────────────────────────────────────────────
def classify_breed_ai(breed: str, city: str = "") -> Tuple[str, str]:
    """阶段 3：调 AI 串行分类（单条；批次由 pipeline 控制）。

    Args:
        breed: 清洗后的品种名
        city:  城市 key（用于 AI 缓存分区）

    Returns:
        (category, source)
        - AI 成功: (category, 'ai')
        - AI 失败: ('其他', 'ai_fallback')
    """
    if not breed:
        return ("其他", "ai_fallback")
    try:
        from gov_price_etl.ai.service import classify_breed_batch
        result = classify_breed_batch([breed], city)
        cat = result.get(breed, "其他")
        if cat and cat != "其他":
            return (cat, "ai")
        return ("其他", "ai_fallback")
    except Exception:
        return ("其他", "ai_fallback")


# ── 兼容旧接口：三段合并 ────────────────────────────────────────────────
def classify_breed(breed: str, spec: str = "", city: str = "") -> str:
    """兼容旧接口：返回 category 字符串。

    流程：
      1. 本地 DB 精确匹配
      2. 本地 DB 模糊召回
      3. （不再调 AI —— AI 由 ETL pipeline 显式发起）

    如需完整三段（含 AI），请用 `classify_breed_with_stages()` 或在 pipeline 中显式编排。
    """
    cat, _src = classify_breed_local(breed)
    return cat or "其他"


def classify_breed_with_stages(breed: str, city: str = "",
                               ai_threshold: float = 0.45,
                               use_ai: bool = True) -> Tuple[str, str, str]:
    """三段式完整流程（pipeline 编排用）。

    Args:
        breed:        清洗后的品种名
        city:         城市 key（AI 缓存分区用）
        ai_threshold: 阶段 2 Jaccard 阈值
        use_ai:       是否在阶段 1+2 未命中时调 AI

    Returns:
        (category, source, stage)
        - category: 分类名（兜底 '其他'）
        - source:   'db_exact' / 'db_fuzzy' / 'ai' / 'ai_fallback'
        - stage:    '1' / '2' / '3'（命中所在阶段）
    """
    # 阶段 1: DB 精确
    cat, src = classify_breed_db_exact(breed)
    if cat:
        return (cat, src, "1")
    # 阶段 2: DB 模糊
    cat, src = classify_breed_db_fuzzy(breed, threshold=ai_threshold)
    if cat:
        return (cat, src, "2")
    # 阶段 3: AI 串行
    if use_ai:
        cat, src = classify_breed_ai(breed, city)
        return (cat, src, "3")
    return ("其他", "", "")


# ── AI 分类回退（透传到 ai.service，兼容旧调用） ─────────────────────────
def _fetch_ai_category_batch(breeds: list, city: str) -> dict:
    """批量查询 AI 分类（仅对未命中品种调 API），返回 {breed: category}。

    实现：透传到 ai.service.classify_breed_batch（自带缓存 + 统一网关调用）。
    """
    if not breeds:
        return {}
    try:
        from gov_price_etl.ai.service import classify_breed_batch
        return classify_breed_batch(breeds, city)
    except Exception as e:
        return {b: "其他" for b in breeds}


# 进程内缓存（同进程内同 breed 不重复分类）
_ai_cache: dict = {}


# ── 私有：DB 连接 ───────────────────────────────────────────────────────
# 注：旧的 _get_db_conn() 已替换为 _get_category_db_conn()，
#     内部连 CATEGORY_RULES_DB（breed_category_rules.db）而非 SPEC_RULES_DB。
#     旧的"借 vec_store 连接"实现有 bug（指向错误的 DB 文件），现已修正。

if __name__ == "__main__":
    import sys
    breed = sys.argv[1] if len(sys.argv) > 1 else ""
    city = sys.argv[2] if len(sys.argv) > 2 else ""
    cat, src, stage = classify_breed_with_stages(breed, city)
    print(f"品种: {breed} | 分类: {cat} | source: {src} | stage: {stage}")
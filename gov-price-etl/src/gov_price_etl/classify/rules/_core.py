"""classify/rules/_core.py - 核心分类函数

breed → category 三级召回：
  1. Jaccard 相似度（精确包含 + 加权 + char-bigram，阈值 0.45）
  2. DB breed_category_rules 精确查表
  3. 未命中 → "其他"（由 etl.py 单独发起 AI 批量分类）

路径与导入已统一通过 `gov_price_etl.*` 命名空间处理，不再用 sys.path 黑魔法。
"""
import os
import sys

from gov_price_etl.paths import CATEGORY_RULES_DB
from gov_price_etl.parse_spec.rules.vector_store import get_vec_store

# ── 复用 VecStore 的持久连接 ───────────────────────────────────────────
def _get_db_conn():
    """Return the persistent sqlite3 connection from VecStore."""
    return get_vec_store()._get_conn()


# ── AI 分类回退（透传到 ai.service） ────────────────────────────────────
def _fetch_ai_category_batch(breeds: list[str], city: str) -> dict:
    """批量查询 AI 分类（仅对未命中品种调 API），返回 {breed: category}

    实现：透传到 ai.service.classify_breed_batch（自带缓存 + 统一网关调用）
    """
    if not breeds:
        return {}
    try:
        from gov_price_etl.ai.service import classify_breed_batch
        return classify_breed_batch(breeds, city)
    except Exception as e:
        # 兑底：避免破坏调用方
        return {b: "其他" for b in breeds}


# 进程内缓存（同进程内同 breed 不重复分类）
_ai_cache: dict = {}


def classify_breed(breed: str, spec: str = "", city: str = "") -> str:
    """
    breed → category 分类。
    流程：
      1. Jaccard 召回（精确包含 + 加权 Jaccard + char-jaccard，阈值 0.45）
      2. 未命中 → "其他"（AI 批量处理）
    """
    if not breed:
        return "其他"

    breed_val = breed.strip()

    # 1. Jaccard 召回
    try:
        from gov_price_etl.classify.rules.jaccard import jaccard_breed_classify
        cat, score = jaccard_breed_classify(breed_val)
        if cat:
            return cat
    except Exception:
        pass

    return "其他"


if __name__ == "__main__":
    import sys
    breed = sys.argv[1] if len(sys.argv) > 1 else ""
    spec = sys.argv[2] if len(sys.argv) > 2 else ""
    city = sys.argv[3] if len(sys.argv) > 3 else "xian"
    print(f"品种: {breed} | 规格: {spec} → 分类: {classify_breed(breed, spec, city)}")

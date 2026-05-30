# classify/rules/_core.py - 核心分类函数（已重构为 Jaccard 召回 + AI fallback）
import os, re, sys

# ── 复用 VecStore 的持久连接（per-process 单例）──────────────────────────────
from parse_spec.rules.vector_store import get_vec_store

def _get_db_conn():
    """Return the persistent sqlite3 connection from VecStore."""
    return get_vec_store()._get_conn()

# ── 提前初始化 import path（避免每条记录重复改 sys.path）────────────────────

_JACCARD_LOADED = False
def _ensure_jaccard():
    global _JACCARD_LOADED
    if not _JACCARD_LOADED:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        _JACCARD_LOADED = True

# 缓存
_ai_cache = {}

def _query_breed_rules_db(breeds: list[str]) -> dict:
    """仅查 breed_category_rules.db 精确匹配，不调 API，返回 {breed: category}"""
    if not breeds:
        return {}
    rules_db = "/Users/pengfit/.openclaw/workspace/skills/gov-price-etl/commands/classify/rules/breed_category_rules.db"
    result = {}
    if os.path.exists(rules_db):
        conn = _get_db_conn()
        c = conn.cursor()
        placeholders = ",".join("?" for _ in breeds)
        c.execute(f"SELECT breed, category FROM breed_category_rules WHERE breed IN ({placeholders})", breeds)
        for row in c.fetchall():
            result[row[0]] = row[1]
            _ai_cache[row[0]] = row[1]
    return result



def _fetch_ai_category_batch(breeds: list[str], city: str) -> dict:
    """批量查询 AI 分类（仅对未命中品种调 API），返回 {breed: category}"""
    if not breeds:
        return {}
    import http.client, json as _json
    from classify import _ai_cache
    # 先从缓存补齐
    uncached = [b for b in breeds if b not in _ai_cache]
    if uncached:
        try:
            body = _json.dumps({"breeds": uncached, "city": city}).encode("utf-8")
            conn = http.client.HTTPConnection("localhost", 5200, timeout=60)
            conn.request("POST", "/api/stats/spec-quality/classify-breed-batch", body=body,
                      headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            data = _json.loads(resp.read())
            if data.get("ok"):
                for breed, r in data.get("results", {}).items():
                    _ai_cache[breed] = r.get("category", "其他")
            else:
                for b in uncached:
                    _ai_cache.setdefault(b, "其他")
        except Exception:
            for b in uncached:
                _ai_cache.setdefault(b, "其他")
    return {b: _ai_cache.get(b, "其他") for b in breeds}


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
        _ensure_jaccard()
        from classify.rules.jaccard import jaccard_breed_classify
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
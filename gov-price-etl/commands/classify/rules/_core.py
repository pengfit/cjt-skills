# classify/rules/_core.py - 核心分类函数（已重构为 Jaccard 召回 + AI fallback）
import os, re, sys

try:
    from . import CLASSIFICATIONS, RULES_DIR
except ImportError:
    from classify.rules import CLASSIFICATIONS, RULES_DIR

# 缓存
_ai_cache = {}


def _fetch_ai_category(breed_clean: str, city: str) -> str:
    """调 AI 补充分类（带内存缓存，同一 breed 只查一次）"""
    if breed_clean in _ai_cache:
        return _ai_cache[breed_clean]
    # 调批量 API（单条）
    result = _fetch_ai_category_batch([breed_clean], city)
    cat = result.get(breed_clean, "其他")
    _ai_cache[breed_clean] = cat
    return cat


def _fetch_ai_category_batch(breeds: list[str], city: str) -> dict:
    """批量查询 AI 分类，返回 {breed: category}（带内存缓存 + DB 直查）"""
    if not breeds:
        return {}
    import sqlite3, http.client, json as _json
    rules_db = "/Users/pengfit/.openclaw/workspace/skills/gov-price-etl/commands/parse_spec/rules/rules_vec.db"
    # ── Step 1: DB 直查（不走 API）──
    db_cached = {}
    if os.path.exists(rules_db):
        conn = sqlite3.connect(rules_db)
        c = conn.cursor()
        placeholders = ",".join("?" for _ in breeds)
        c.execute(f"SELECT breed, category FROM breed_category_rules WHERE breed IN ({placeholders})", breeds)
        for row in c.fetchall():
            db_cached[row[0]] = row[1]
            _ai_cache[row[0]] = row[1]
        conn.close()
    # ── Step 2: 未命中品种调 API ──
    uncached = [b for b in breeds if b not in _ai_cache]
    if uncached:
        try:
            body = _json.dumps({"breeds": uncached, "city": city}).encode("utf-8")
            conn = http.client.HTTPConnection("localhost", 5200, timeout=120)
            conn.request("POST", "/api/stats/spec-quality/classify-breed-batch", body=body,
                      headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            data = _json.loads(resp.read())
            if data.get("ok"):
                for breed, r in data.get("results", {}).items():
                    _ai_cache[breed] = r.get("category", "其他")
        except Exception:
            for b in uncached:
                _ai_cache.setdefault(b, "其他")
    return {b: _ai_cache.get(b, "其他") for b in breeds}


def classify_breed(breed: str, spec: str = "", city: str = "") -> str:
    """
    breed → category 分类。
    流程：
      1. Jaccard 召回（来自 jaccard.py）
      2. 未命中 → AI 补充分类
      3. AI 结果反向写入 rules_vec.db（下次直接命中）
    """
    if not breed:
        return "其他"

    breed_val = breed.strip()

    # 1. Jaccard 召回
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from jaccard import jaccard_breed_classify, insert_breed_rule
        cat = jaccard_breed_classify(breed_val)
        if cat:
            return cat
    except Exception:
        pass

    # 2. AI fallback（仅在 Jaccard 未命中时触发）
    if city:
        cat = _fetch_ai_category(breed_val, city)
        # 反向写入 rules_vec.db，供下次召回
        try:
            from jaccard import insert_breed_rule
            insert_breed_rule(breed_val, cat, source="ai")
        except Exception:
            pass
        return cat

    return "其他"


def get_all_categories() -> list:
    return sorted(CLASSIFICATIONS)


CAT_ID_MAP = {name: idx + 1 for idx, name in enumerate(sorted(CLASSIFICATIONS))}


if __name__ == "__main__":
    import sys
    breed = sys.argv[1] if len(sys.argv) > 1 else ""
    spec = sys.argv[2] if len(sys.argv) > 2 else ""
    city = sys.argv[3] if len(sys.argv) > 3 else "xian"
    print(f"品种: {breed} | 规格: {spec} → 分类: {classify_breed(breed, spec, city)}")
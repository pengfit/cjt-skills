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
    import http.client, json as _json
    try:
        body = _json.dumps({"breed": breed_clean, "city": city}).encode("utf-8")
        c = http.client.HTTPConnection("localhost", 5200, timeout=15)
        c.request("POST", "/api/stats/spec-quality/classify-breed", body=body,
                  headers={"Content-Type": "application/json"})
        resp = c.getresponse()
        data = _json.loads(resp.read())
        cat = data.get("category", "其他") if data.get("ok") else "其他"
    except Exception:
        cat = "其他"
    _ai_cache[breed_clean] = cat
    return cat


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
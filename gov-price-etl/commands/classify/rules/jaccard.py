"""jaccard.py - 基于 Jaccard 相似度的品种→分类召回引擎"""

import sqlite3, os
from functools import lru_cache

RULES_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "parse_spec", "rules", "rules_vec.db")
DEFAULT_THRESHOLD = 0.35


def _ngrams(s: str, n: int = 2) -> frozenset:
    s = s.strip()
    if len(s) < n:
        return frozenset([s]) if s else frozenset()
    return frozenset(s[i:i+n] for i in range(len(s)-n+1))


def jaccard(s1: str, s2: str, n: int = 2) -> float:
    """基于 n-gram 的 Jaccard 相似度，n=2 即字符 bigram"""
    a = _ngrams(s1, n)
    b = _ngrams(s2, n)
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def _load_breed_rules() -> list:
    """从 classify/rules/ 提取 breed→category 原始映射，按 breed 长度降序排列优先匹配"""
    result = []
    rules_dir = os.path.join(os.path.dirname(__file__), "classify", "rules")
    for fname in ["breed.py", "keyword.py", "species.py"]:
        fpath = os.path.join(rules_dir, fname)
        if not os.path.exists(fpath):
            continue
        for line in open(fpath):
            line = line.strip()
            if '\u2192' not in line or line.startswith('#'):
                continue
            try:
                breed_part, cat_part = line.split('\u2192', 1)
                breed = breed_part.strip().strip('"').strip("'")
                cat = cat_part.strip().strip('"').strip("'")
                if breed and cat:
                    result.append((breed, cat))
            except Exception:
                pass
    # 优先匹配更长的 breed（如"镀锌钢管"优先于"钢管"）
    result.sort(key=lambda x: len(x[0]), reverse=True)
    return result


def _load_db_rules() -> list:
    """从 rules_vec.db 提取 breed 非空的规则"""
    if not os.path.exists(RULES_DB):
        return []
    conn = sqlite3.connect(RULES_DB)
    c = conn.cursor()
    c.execute("SELECT DISTINCT breed, category FROM breed_category_rules WHERE breed != '' AND category != ''")
    rows = c.fetchall()
    conn.close()
    return rows


@lru_cache(maxsize=5000)
def jaccard_breed_classify(breed_clean: str, threshold: float = DEFAULT_THRESHOLD) -> str:
    """
    用 Jaccard 相似度召回已知 breed，推断 category。
    优先用精确匹配（按长度降序）；未命中则找最高相似度 > threshold 的记录。
    返回空字符串表示未命中。
    """
    if not breed_clean:
        return ""

    static_rules = _load_breed_rules()
    db_rules = _load_db_rules()
    all_rules = static_rules + db_rules

    # 1. 精确匹配（按长度降序，优先更长匹配）
    for known_breed, cat in all_rules:
        if known_breed in breed_clean or breed_clean in known_breed:
            return cat

    # 2. Jaccard 相似度召回
    best_score = 0.0
    best_cat = ""
    for known_breed, cat in all_rules:
        score = jaccard(breed_clean, known_breed, n=2)
        if score > best_score:
            best_score = score
            best_cat = cat

    if best_score >= threshold:
        return best_cat
    return ""


def insert_breed_rule(breed: str, category: str, source: str = "ai", note: str = ""):
    """将 AI 分类结果或手动确认结果写入 breed_category_rules 表，供下次召回"""
    if not breed or not category:
        return
    if not os.path.exists(RULES_DB):
        return
    conn = sqlite3.connect(RULES_DB)
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO breed_category_rules (breed, category, source, note) VALUES (?, ?, ?, ?)",
        (breed, category, source, note)
    )
    conn.commit()
    conn.close()
    jaccard_breed_classify.cache_clear()
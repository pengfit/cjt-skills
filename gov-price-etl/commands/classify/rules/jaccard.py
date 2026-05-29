"""jaccard.py - 基于分词 + 主体词权重 Jaccard 的品种→分类召回引擎"""

import sqlite3, os, re
from functools import lru_cache

try:
    import jieba
    _HAS_JIEBA = True
except ImportError:
    _HAS_JIEBA = False

RULES_DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "parse_spec", "rules", "rules_vec.db"
)
# Jaccard 召回阈值：≥0.8 才接受分类，否则回退到 AI 批量分类
DEFAULT_THRESHOLD = 0.45

# ── per-process 持久连接 ─────────────────────────────────────────────────────
_DB_CONN = None
def _get_db_conn():
    global _DB_CONN
    if _DB_CONN is None:
        from parse_spec.rules.vector_store import get_vec_store
        _DB_CONN = get_vec_store()._get_conn()
    return _DB_CONN


def _segment(breed: str) -> list:
    """
    品牌名称分词。
    - 有 jieba：精确模式分词，去除单字词
    - 无 jieba：按字符 n-gram 回退
    """
    if not breed:
        return []
    # 预处理：去除数字、括号、计量单位
    raw = re.sub(r'[\d\.\-（）()×x米m²㎡cmmm³立方升L件个片张块根米/吨元]', ' ', breed)
    raw = raw.strip()

    if _HAS_JIEBA:
        words = [w.strip() for w in jieba.cut(raw, cut_all=False)]
        # 去除单字和空白
        words = [w for w in words if len(w) >= 2]
    else:
        # 回退：保留所有字符 bigram/tetragram
        words = []
        s = raw.replace(' ', '')
        for n in (4, 3, 2):
            for i in range(len(s) - n + 1):
                words.append(s[i:i+n])
        words = list(set(words))

    return words


def _word_weight(word: str) -> float:
    """
    词权重 = 长度 × 长度（长词权重更高）。
    "混凝土" 权重 16 vs "透水" 权重 4，
    确保主体词命中时总分更高。
    """
    return len(word) * len(word)


def _weighted_jaccard(words1: list, words2: list) -> float:
    """
    加权 Jaccard：词集合相似度，权重由词长度决定。
    score = Σ min(w_i∩w_j) / Σ max(w_i∪w_j)
    其中 w_i = _word_weight(词i)
    """
    if not words1 or not words2:
        return 0.0

    set1 = set(words1)
    set2 = set(words2)

    intersection = set1 & set2
    union = set1 | set2

    weighted_inter = sum(_word_weight(w) for w in intersection)
    weighted_union = sum(_word_weight(w) for w in union)

    if weighted_union == 0:
        return 0.0
    return weighted_inter / weighted_union


def _char_jaccard(s1: str, s2: str, n: int = 2) -> float:
    """基于字符 n-gram 的标准 Jaccard（用于混合增强）"""
    def ngrams(s, n):
        s = s.strip()
        if len(s) < n:
            return frozenset([s]) if s else frozenset()
        return frozenset(s[i:i+n] for i in range(len(s)-n+1))
    a = ngrams(s1, n)
    b = ngrams(s2, n)
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def _load_breed_rules() -> list:
    """从 classify/rules/ 提取 breed→category 原始映射，按 breed 长度降序排列"""
    result = []
    rules_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
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
    result.sort(key=lambda x: len(x[0]), reverse=True)
    return result


def _load_db_rules() -> list:
    """从 rules_vec.db 提取 breed 非空的规则"""
    if not os.path.exists(RULES_DB):
        return []
    conn = _get_db_conn()
    c = conn.cursor()
    c.execute(
        "SELECT DISTINCT breed, category FROM breed_category_rules WHERE breed != '' AND category != ''"
    )
    return c.fetchall()


@lru_cache(maxsize=5000)
def jaccard_breed_classify(breed_clean: str, threshold: float = DEFAULT_THRESHOLD) -> tuple:
    """
    品种→分类召回，分两阶段：
    1. 精确包含匹配（优先更长 breed）
    2. 加权 Jaccard 召回（分词 + 主体词权重）
       混合 char-jaccard 增强，防止分词切碎导致遗漏
    返回 (category, score)。score < threshold 时 category 为空字符串。
    """
    if not breed_clean:
        return ("", 0.0)

    static_rules = _load_breed_rules()
    db_rules = _load_db_rules()
    all_rules = static_rules + db_rules

    # 1. 精确包含匹配（仅当 know_breed 是完整词，避免子串误匹配）
    # 例：花岗岩石材 ≠ 花岗岩石材止车石（除非止车石是独立后缀）
    def _is_word_match(query: str, known: str) -> bool:
        """query 包含 know_breed，且 know_breed 左边是词边界或 query，右边是词边界或 end-of-string"""
        if known not in query:
            return False
        idx = query.index(known)
        left_ok = (idx == 0) or (query[idx - 1].isspace()) or (query[idx - 1] in '（()[]【】')
        right_pos = idx + len(known)
        right_ok = (right_pos >= len(query)) or (query[right_pos].isspace()) or (query[right_pos] in '）()[]、【】,.，,')
        return left_ok and right_ok

    exact_matches = [(known_breed, cat) for known_breed, cat in all_rules
                    if _is_word_match(breed_clean, known_breed) or _is_word_match(known_breed, breed_clean)]
    if exact_matches:
        # 选最长的匹配词
        best = max(exact_matches, key=lambda x: len(x[0]))
        return (best[1], 1.0)

    # 2. 加权 Jaccard 召回
    breed_words = _segment(breed_clean)
    best_score = 0.0
    best_cat = ""

    for known_breed, cat in all_rules:
        known_words = _segment(known_breed)

        # 加权词 Jaccard（主体词优先）
        word_score = _weighted_jaccard(breed_words, known_words)

        # 混合字符 Jaccard（防止分词切碎导致漏匹配）
        char_score = _char_jaccard(breed_clean, known_breed, n=2)

        # 综合分数：词 Jaccard 为主，字符 Jaccard 辅助
        score = 0.7 * word_score + 0.3 * char_score

        if score > best_score:
            best_score = score
            best_cat = cat

    if best_score >= threshold:
        return (best_cat, best_score)
    return None



def insert_breed_rule(breed: str, category: str, source: str = "ai", confidence: float = 1.0, note: str = ""):
    """将分类结果写入 breed_category_rules 表"""
    if not breed or not category:
        return
    if not os.path.exists(RULES_DB):
        return
    conn = _get_db_conn()
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO breed_category_rules (breed, category, source, confidence, note) VALUES (?, ?, ?, ?, ?)",
        (breed, category, source, confidence, note)
    )
    conn.commit()
    jaccard_breed_classify.cache_clear()

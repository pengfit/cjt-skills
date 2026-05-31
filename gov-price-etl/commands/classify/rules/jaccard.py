"""jaccard.py - 高性能品种→分类召回引擎
优化策略：
  1. 规则预分词缓存（加载时完成，classify 时零重复计算）
  2. Exact match 倒排索引（O(1) 精确匹配，非 O(n) 遍历）
  3. _segment() LRU 缓存（高频品种重复分词 0 开销）
  4. Dice 系数替代 char Jaccard（更直观，区分度更高）
  5. 主体词判定：全局词频加权，过滤高频噪声词
  6. 评分权重：mat=0.55 / word=0.30 / char=0.15（已固定）
  7. 规则合并去重（加载时完成）
"""

import os, re, unicodedata, threading
from functools import lru_cache
from collections import Counter

try:
    import jieba
    _HAS_JIEBA = True
except ImportError:
    _HAS_JIEBA = False

# ── 常量 ──────────────────────────────────────────────────────────────────────

RULES_DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "classify", "rules", "breed_category_rules.db"
)
DEFAULT_THRESHOLD = 0.45

# 全局停用词（过短无意义词，主体词判定时跳过）
_STOP_WORDS = frozenset([
    "的", "和", "与", "及", "或", "等", "规格", "型号", "品牌",
    "型", "类", "级", "种", "批", "件", "个", "米", "平方", "立方",
])

# ── DB 连接 ───────────────────────────────────────────────────────────────────

_DB: sqlite3.Connection | None = None
_DB_LOCK = threading.Lock()

def _get_rules_db_conn() -> sqlite3.Connection:
    global _DB
    if _DB is None:
        with _DB_LOCK:
            if _DB is None:
                import sqlite3
                _DB = sqlite3.connect(RULES_DB, check_same_thread=False)
                _DB.row_factory = sqlite3.Row
    return _DB

# ── 文本正规化 ────────────────────────────────────────────────────────────────

NORMALIZE_MAP = {
    "钢筋砼": "钢筋混凝土",
    "砼": "混凝土",
    "Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV", "Ⅴ": "V",
    "一级": "I级", "二级": "II级", "三级": "III级",
}

def normalize_breed(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.strip()
    for k, v in NORMALIZE_MAP.items():
        text = text.replace(k, v)
    return text

# ── 分词（LRU 缓存）───────────────────────────────────────────────────────────

@lru_cache(maxsize=10000)
def _segment(raw: str) -> frozenset:
    """
    返回 frozenset[str]，方便直接做集合运算。
    缓存命中率极高——同一品种只计算一次。
    """
    if not raw:
        return frozenset()
    raw = normalize_breed(raw.strip())
    words = []

    if _HAS_JIEBA:
        words.extend(
            w.strip()
            for w in jieba.cut(raw, cut_all=False)
            if len(w.strip()) >= 2
        )

    # 字符 n-gram（3-4 字），仅有效字符
    s = raw.replace(" ", "")
    for n in (4, 3):
        for i in range(len(s) - n + 1):
            words.append(s[i:i+n])

    # 去停用词
    return frozenset(w for w in words if w not in _STOP_WORDS)

# ── 相似度 ────────────────────────────────────────────────────────────────────

def _word_weight(word: str) -> float:
    """词权重：长度越大权重越高，上限 8。"""
    return min(len(word), 8)

def _dice(s1: str, s2: str, n: int = 2) -> float:
    """
    字符 n-gram Dice 系数。
    dice = 2 * |A ∩ B| / (|A| + |B|)
    比 Jaccard 更敏感，适合短文本匹配。
    """
    def ngrams(s: str, n: int):
        s = s.strip()
        if len(s) < n:
            return frozenset([s]) if s else frozenset()
        return frozenset(s[i:i+n] for i in range(len(s)-n+1))
    a, b = ngrams(s1, n), ngrams(s2, n)
    if not a or not b:
        return 0.0
    return 2.0 * len(a & b) / (len(a) + len(b))

# ── 规则加载（预分词 + 去重 + 索引构建）──────────────────────────────────────────

# 缓存结构（进程全局）
_ALL_RULES: list[tuple[str, str, frozenset]] | None = None   # (breed, category, words)
_EXACT_INDEX: dict[str, list[tuple[str, str, frozenset]]] | None = None  # word → rules containing it
_GLOBAL_WORD_FREQ: Counter | None = None                     # word → 出现次数（用于主体词判定）
_ALL_RULES_LOCK = threading.Lock()

def _load_all_rules() -> tuple[
    list[tuple[str, str, frozenset]],
    dict[str, list[tuple[str, str, frozenset]]],
    Counter,
]:
    """
    返回 (rules, exact_index, word_freq_counter)。
    rules: [(breed, category, words_frozenset), ...]
    exact_index: word → 包含该词的规则列表（用于精确匹配加速）
    word_freq: 全局词频（用于主体词判定）
    """
    # 1. 从文本文件加载
    raw_rules: dict[str, str] = {}  # breed_normalized → category（去重，保留第一个）
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
                breed = normalize_breed(breed_part.strip().strip('"').strip("'"))
                cat = cat_part.strip().strip('"').strip("'")
                if breed and cat and breed not in raw_rules:
                    raw_rules[breed] = cat
            except Exception:
                pass

    # 2. 从 DB 加载并追加（不覆盖文本规则）
    if os.path.exists(RULES_DB):
        try:
            conn = _get_rules_db_conn()
            c = conn.cursor()
            c.execute(
                "SELECT breed, category FROM breed_category_rules "
                "WHERE breed != '' AND category != ''"
            )
            for breed, cat in c.fetchall():
                b_norm = normalize_breed(breed)
                if b_norm and b_norm not in raw_rules:
                    raw_rules[b_norm] = cat
        except Exception:
            pass

    # 3. 全局词频统计（预分词时一并收集）
    word_freq: Counter = Counter()

    # 4. 构建规则列表 + 预分词 + 精确匹配索引
    rules: list[tuple[str, str, frozenset]] = []
    for breed, cat in raw_rules.items():
        words = _segment(breed)
        rules.append((breed, cat, words))
        for w in words:
            word_freq[w] += 1

    # 按 breed 长度降序（长词优先精确匹配）
    rules.sort(key=lambda x: len(x[0]), reverse=True)

    # 5. 构建精确匹配索引（word → 包含该词的规则，按 breed 长度降序）
    exact_index: dict[str, list[tuple[str, str, frozenset]]] = {}
    for breed, cat, words in rules:
        for w in words:
            if w not in exact_index:
                exact_index[w] = []
            exact_index[w].append((breed, cat, words))
    # 索引内也按 breed 长度降序
    for w in exact_index:
        exact_index[w].sort(key=lambda x: len(x[0]), reverse=True)

    return rules, exact_index, word_freq

def _get_all_rules() -> list[tuple[str, str, frozenset]]:
    global _ALL_RULES
    if _ALL_RULES is not None:
        return _ALL_RULES
    with _ALL_RULES_LOCK:
        if _ALL_RULES is not None:
            return _ALL_RULES
        global _EXACT_INDEX, _GLOBAL_WORD_FREQ
        _ALL_RULES, _EXACT_INDEX, _GLOBAL_WORD_FREQ = _load_all_rules()
        return _ALL_RULES

def _get_exact_index() -> dict:
    _ = _get_all_rules()   # 确保已初始化
    return _EXACT_INDEX

def _get_word_freq() -> Counter:
    _ = _get_all_rules()
    return _GLOBAL_WORD_FREQ

# ── 主体词判定（全局词频加权）────────────────────────────────────────────────────

def _material_word_score(query_words: frozenset, breed_words: frozenset,
                         word_freq: Counter) -> float:
    """
    主体词覆盖率。
    - 词长 ≥3
    - 在 breed 中存在
    - 词频越高（越像核心词）权重越大；但过高频词（>90% 规则出现）反而降权
    """
    total = word_freq.total()
    if not query_words or total == 0:
        return 0.0

    score = 0.0
    for w in query_words:
        if len(w) >= 3 and w in breed_words:
            freq = word_freq[w] / total
            # 极高频词（出现在 >50% 规则）降低权重，<10% 高频词加权
            if freq > 0.5:
                weight = 0.3
            elif freq > 0.1:
                weight = 0.8
            else:
                weight = 1.0
            score += weight

    # 归一化：除以 query 中有效词数
    valid_q = sum(1 for w in query_words if len(w) >= 3)
    return score / valid_q if valid_q else 0.0

# ── 核心召回 ──────────────────────────────────────────────────────────────────

def _is_word_match(query: str, known: str) -> bool:
    """
    query 在词边界意义上完整包含 known。
    宽容规则：known 是 query 后缀，且前缀为规格字符 → 匹配。
    """
    if known not in query:
        return False
    idx = query.index(known)
    right_pos = idx + len(known)
    right_ok = (right_pos >= len(query)
                or query[right_pos].isspace()
                or query[right_pos] in '）()[]、【】,.，,')
    if not right_ok:
        return False
    left_ok = (idx == 0 or query[idx-1].isspace()
               or query[idx-1] in '（()[]【】')
    if left_ok:
        return True
    if idx > 0 and idx + len(known) == len(query):
        if re.fullmatch(r'[\w.\-]+', query[:idx]):
            return True
    return False


@lru_cache(maxsize=5000)
def jaccard_breed_classify(breed_clean: str,
                            threshold: float = DEFAULT_THRESHOLD) -> tuple[str, float]:
    """
    品种→分类召回。
    1. 精确包含匹配（倒排索引 O(k)，k=query词数）
    2. 加权 Jaccard + Dice 召回（权重: mat=0.55 / word=0.30 / char=0.15）
    返回 (category, score)。score < threshold 时 category 为空。
    """
    if not breed_clean:
        return ("", 0.0)

    all_rules = _get_all_rules()
    exact_index = _get_exact_index()
    word_freq = _get_word_freq()
    breed_words = _segment(breed_clean)

    # ── 1. 精确包含匹配（通过倒排索引）──────────────────────────
    # 收集 query 中的候选词（长度≥3）
    candidate_rules: dict[str, tuple[str, str, frozenset]] = {}
    for w in breed_words:
        if len(w) < 3:
            continue
        for rule in exact_index.get(w, ()):
            breed_key = rule[0]
            if breed_key not in candidate_rules:
                candidate_rules[breed_key] = rule

    if candidate_rules:
        # 候选规则中做完整匹配
        exact_matches = [
            (breed_key, rule[1])
            for breed_key, rule in candidate_rules.items()
            if _is_word_match(breed_clean, breed_key) or _is_word_match(breed_key, breed_clean)
        ]
        if exact_matches:
            best_breed, best_cat = max(exact_matches, key=lambda x: len(x[0]))
            return (best_cat, 1.0)

    # ── 2. Jaccard 召回 ────────────────────────────────────────
    best_score = 0.0
    best_cat = ""

    for known_breed, cat, known_words in all_rules:
        mat = _material_word_score(breed_words, known_words, word_freq)

        # 加权 Jaccard（分词语义）
        inter = breed_words & known_words
        union = breed_words | known_words
        w_inter = sum(_word_weight(w) for w in inter)
        w_union = sum(_word_weight(w) for w in union)
        word_score = w_inter / w_union if w_union else 0.0

        # Dice 系数（字符级，bigram=2 更适合中文短词）
        char_score = _dice(breed_clean, known_breed, n=2)

        # 综合权重
        if mat > 0:
            score = 0.55 * mat + 0.30 * word_score + 0.15 * char_score
        else:
            score = 0.20 * word_score + 0.80 * char_score

        if score > best_score:
            best_score = score
            best_cat = cat

    if best_score >= threshold:
        return (best_cat, best_score)
    return ("", 0.0)


def insert_breed_rule(breed: str, category: str, source: str = "ai",
                      confidence: float = 1.0, note: str = ""):
    """写入单条 breed_category_rules 表（幂等）。"""
    global _ALL_RULES, _EXACT_INDEX, _GLOBAL_WORD_FREQ
    try:
        conn = _get_rules_db_conn()
        conn.execute(
            "INSERT OR IGNORE INTO breed_category_rules "
            "(breed, category, source, confidence, note) VALUES (?, ?, ?, ?, ?)",
            (breed, category, source, confidence, note)
        )
        conn.commit()
        _ALL_RULES = None
        _EXACT_INDEX = None
        _GLOBAL_WORD_FREQ = None
    except Exception:
        pass


def batch_insert_breed_rules(breed_category_pairs: list[tuple[str, str, str, float, str]]):
    """
    批量写入 breed_category_rules 表（幂等，事务提交）。
    写入后自动清除规则缓存，下次 classify 时重新加载。

    Args:
        breed_category_pairs: list of (breed, category, source, confidence, note)
    """
    global _ALL_RULES, _EXACT_INDEX, _GLOBAL_WORD_FREQ
    if not breed_category_pairs:
        return
    try:
        conn = _get_rules_db_conn()
        conn.executemany(
            "INSERT OR IGNORE INTO breed_category_rules "
            "(breed, category, source, confidence, note) VALUES (?, ?, ?, ?, ?)",
            breed_category_pairs
        )
        conn.commit()
        _ALL_RULES = None
        _EXACT_INDEX = None
        _GLOBAL_WORD_FREQ = None
    except Exception:
        pass
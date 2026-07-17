#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parse_spec/rules/vector_store.py
Rule vector store with SQLite + blob persistence.
Keyword-set similarity search with category/breed filtering.
"""
import json, os, re, glob, threading, math
import numpy as np
import sqlite3

from gov_price_etl.paths import SPEC_RULES_DB, PROJECT_ROOT

# 向后兼容：旧代码可能 import RULES_DIR / DB_PATH
RULES_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = str(SPEC_RULES_DB)


# ── Keyword-set similarity (zero-dep) ────────────────────────────────────────

KEYWORD_STOPWORDS = frozenset([
    "a", "an", "the", "for", "of", "in", "on", "at", "to", "with",
    "and", "or", "is", "was", "are", "been", "be", "as", "by", "from",
    "规则", "pattern", "attr", "用于", "rule",
])


def _tokenize(text: str) -> set:
    """Simple Chinese-aware tokenization."""
    if not text:
        return set()
    tokens = re.findall(r"[\u4e00-\u9fff]+|[A-Za-z]+|[0-9.]+", text.lower())
    return {t for t in tokens if t not in KEYWORD_STOPWORDS and len(t) > 1}


def _keyword_score(spec_tokens: set, rule_tokens: frozenset | set) -> float:
    """Jaccard similarity between token sets."""
    if not spec_tokens or not rule_tokens:
        return 0.0
    inter = len(spec_tokens & rule_tokens)
    union = len(spec_tokens | rule_tokens)
    return inter / union if union else 0.0


# ── SQLite schema ─────────────────────────────────────────────────────────────

CREATE_TABLE_SPEC = """
CREATE TABLE IF NOT EXISTS breed_spec_rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern     TEXT    NOT NULL UNIQUE,
    attr        TEXT    NOT NULL,
    note        TEXT    DEFAULT '',
    code        TEXT    DEFAULT '',
    breed       TEXT    DEFAULT '',
    category    TEXT    DEFAULT '',
    tokens      TEXT    DEFAULT '[]',
    created_at  TEXT    DEFAULT (datetime('now', 'localtime'))
)
"""

ENSURE_COLS = """
PRAGMA table_info(breed_spec_rules)
"""

CREATE_TABLE_BREED_CATEGORY = """
CREATE TABLE IF NOT EXISTS breed_category_rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  breed TEXT UNIQUE NOT NULL,
  category TEXT NOT NULL,
  source TEXT DEFAULT 'ai',
  confidence REAL DEFAULT 1.0,
  note TEXT DEFAULT '',
  created_at TEXT DEFAULT (date('now'))
)
"""


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(CREATE_TABLE_SPEC)
    conn.commit()
    cols = {r[1] for r in conn.execute(ENSURE_COLS).fetchall()}
    for col, dtype in [
        ("breed",    "TEXT DEFAULT ''"),
        ("category", "TEXT DEFAULT ''"),
        ("tokens",   "TEXT DEFAULT '[]'"),
    ]:
        if col not in cols:
            conn.execute(f"ALTER TABLE breed_spec_rules ADD COLUMN {col} {dtype}")
    conn.execute(CREATE_TABLE_BREED_CATEGORY)
    conn.commit()
    conn.execute(CREATE_TABLE_BREED_CATEGORY)
    conn.commit()


# ── VecStore ────────────────────────────────────────────────────────────────


def _build_tokens(pattern: str, attr: str, breed: str = "", category: str = "") -> list:
    """
    Detect structural features from the normalized pattern string (literal backslashes,
    NOT regex escapes) and generate semantic tokens for Jaccard matching.
    """
    tags = []
    if '(' in pattern and ')' in pattern:
        tags += ["数字捕获", "数字"]
    if re.search(r'\[dwspn]', pattern):
        tags += ["精确匹配", "格式", "转义字符"]
    if '[' in pattern:
        tags += ["字符类", "非数字"]
    dim_markers = pattern.count('×') + pattern.count('x') + pattern.count('X')
    if dim_markers >= 2:
        tags += ["三段", "LWW", "长宽高", "尺寸"]
    elif dim_markers == 1:
        tags += ["两段", "两尺寸", "尺寸"]
    if '.' in pattern:
        tags += ["小数", "浮点", "尺寸", "数字"]
    if pattern.startswith('^') and pattern.endswith('$'):
        tags += ["精确匹配", "格式"]
    if breed:
        tags.append(breed)
    if category:
        tags.append(category)
    if attr:
        tags.append(attr)
    return list(set(tags))


def _build_spec_tokens(spec: str) -> set:
    """
    从 spec 字符串生成结构语义 tokens，与规则的语义标签对应。
    使 '240×115×90' → {'三段','LWW','长宽高','尺寸','数字'}，
    与规则 tokens {'三段','LWW','长宽高','尺寸'} 产生 Jaccard 交集。
    """
    import re
    tokens = set()
    if not spec:
        return tokens

    # 维度格式检测：数字×数字×数字（或数字x数字x数字）
    dim_pattern = re.findall(r'[\u00d7x×](\d+)', spec)
    if len(dim_pattern) >= 2:
        tokens |= {"三段", "LWW", "长宽高", "尺寸", "数字"}
    elif len(dim_pattern) == 1:
        tokens |= {"两段", "两尺寸", "尺寸", "数字"}

    # 小数/浮点
    if '.' in spec:
        tokens |= {"小数", "浮点", "数字"}

    # 纯数字格式（无中文无字母）
    if re.match(r'^[\d\u00d7x×.\s]+$', spec):
        tokens.add("数字")

    return tokens


# ── 2026-07-05 性能优化：缓存 tokens 解码 + 预编译 regex ─────────────────
# 背景：500 docs 压测 cProfile 显示 1.5M 次 json.loads + 591K 次 re._compile
# 优化：模块级缓存，单例生命周期内有效；DB 文件变更会自动失效（重建 VecStore）
_TOKENS_CACHE: dict = {}
_EMPTY_FROZENSET = frozenset()
_COMPILED_RULE_PATTERN_CACHE: dict = {}  # pattern_str -> compiled_regex or None


def _get_compiled_rule_pattern(pat: str):
    """懒加载 + 模块级缓存：rule pattern → compiled regex。None 表示编译失败。"""
    if pat not in _COMPILED_RULE_PATTERN_CACHE:
        try:
            _COMPILED_RULE_PATTERN_CACHE[pat] = re.compile(pat)
        except re.error:
            _COMPILED_RULE_PATTERN_CACHE[pat] = None
    return _COMPILED_RULE_PATTERN_CACHE[pat]


class VecStore:
    __slots__ = ("db_path", "_lock", "_conn")

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = None  # per-process persistent connection
        with self._lock:
            conn = sqlite3.connect(db_path, timeout=30)
            conn.execute('PRAGMA journal_mode=WAL')
            _ensure_schema(conn)
            conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        """Return the persistent connection, creating it if needed."""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30)
            self._conn.execute('PRAGMA journal_mode=WAL')
            _ensure_schema(self._conn)
        return self._conn

    # ── CRUD ──────────────────────────────────────────────────────────────

    def insert(self, pattern: str, attr: str, note: str = "",
               code: str = "", breed: str = "", category: str = "",
               tokens: list = None, skip_duplicate: bool = False) -> bool:
        """Insert or update a rule. Returns True on success."""
        norm_pat = self._strip_r(pattern)
        tokens   = tokens or _build_tokens(norm_pat, attr, breed, category)
        tok_json = json.dumps(list(tokens))
        with self._lock:
            conn = self._get_conn()
            _ensure_schema(conn)
            if skip_duplicate:
                exists = conn.execute(
                    "SELECT 1 FROM breed_spec_rules WHERE pattern=? AND attr=? AND breed=? AND category=?",
                    (norm_pat, attr, breed or "", category or "")
                ).fetchone()
                if exists:
                    return False
            try:
                conn.execute("""
                    INSERT INTO breed_spec_rules (pattern, attr, note, code, breed, category, tokens)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (norm_pat, attr, note, code, breed, category, tok_json))
            except sqlite3.IntegrityError:
                # pattern 单字段唯一约束冲突（同一 pattern 不同 attr/breed/category 组合）
                return False
            conn.commit()
        return True

    def _row_to_rule(self, row: tuple) -> dict:
        """Map a DB row to a rule dict.

        2026-07-05 优化:缓存 tok_json → tokens frozenset(避免重复 json.loads)。
        v0.7:row 多一列 l3(L3 分项工程),精确匹配 +0.40 最高加权;兼容旧 7 列 row。
        """
        if len(row) >= 8:
            pat, attr, note, code, breed, cat, l3, tok_json = row[:8]
        else:
            pat, attr, note, code, breed, cat, tok_json = row
            l3 = ""
        if tok_json:
            cached = _TOKENS_CACHE.get(tok_json)
            if cached is None:
                cached = frozenset(json.loads(tok_json))
                _TOKENS_CACHE[tok_json] = cached
            tokens = cached
        else:
            tokens = _EMPTY_FROZENSET
        return dict(pattern=pat, attr=attr, note=note or "", code=code or "",
                    breed=breed or "", category=cat or "", l3=l3 or "",
                    tokens=tokens)

    def _validate_rule_code(self, code: str, spec: str, attr: str) -> bool:
        """执行校验：code_block 对给定 spec 能否产出目标 attr 的值。

        解决 breed_spec_rules.db 中向量相似度误匹配问题：
        如 '1.5厚' 匹配到 '真石漆' 的规则（token 交集非零），
        但 code_block 执行后 result['thickness'] 为空的，校验不通过。
        """
        if not code or not spec:
            return False
        try:
            import re as _re
            import warnings as _w
            exec_globals = {"result": {}, "re": _re, "s": spec}
            with _w.catch_warnings():
                _w.simplefilter("ignore", SyntaxWarning)
                exec(code, exec_globals)
            norm_a = attr[5:] if attr.startswith("attr_") else attr
            v = exec_globals["result"].get(norm_a, "")
            return bool(v)
        except Exception:
            return False

    def search(self, spec: str = "", category: str = "", breed: str = "",
               l3: str = "",  # v0.7: L3 分项工程(例 "钢化玻璃"),精确匹配 +0.40 最高加权
               top_k: int = 8, attr_filter: str = "",
               validate_spec: str = None) -> list:
        """
        Keyword similarity search with l3 / breed / category scoring + execution validation.

        参数:
          - spec / category / breed / l3: 查询上下文,用于加权召回
          - top_k: 返回数量
          - attr_filter: 属性名过滤
          - validate_spec: 执行校验用 spec 字符串(传入则对每个规则执行 code_block,
            不产出结果的规则直接剔除,解决向量相似度误匹配问题)

        v0.7 评分规则(三段式优先级):
          - Jaccard 相似度 (0-1)
          + l3 精确匹配: +0.40     (L3 分项,最高优先,例 "建筑玻璃" 不会窜到 "瓷砖")
          + breed 精确匹配: +0.30
          + category 精确匹配: +0.20
          × 空 breed 规则 + 有 breed 查询: ×0.80 (通用规则降权)

        Returns:
            [(score, rule_dict), ...] 按 score 降序,最多 top_k 条
        """
        spec_tokens = _build_spec_tokens(spec or "") or set()
        # _build_spec_tokens 对含字母的 spec（如 Φ14 HRB500E）返回空 set，
        # 此时用 _tokenize 兜底，避免所有规则 score=1.0 打乱排序。
        if not spec_tokens:
            spec_tokens = _tokenize(spec or "") or set()

        with self._lock:
            conn = self._get_conn()
            # Build SQL dynamically: breed='' means "no breed filter"
            # category='' means "no category filter" (skip the AND clause)
            if attr_filter:
                if category:
                    base = "SELECT pattern, attr, note, code, breed, category, l3, tokens FROM breed_spec_rules WHERE attr=? AND category=?"
                    if breed:
                        sql = base + " AND breed=?"
                        rows = conn.execute(sql, (attr_filter, category, breed)).fetchall()
                    else:
                        rows = conn.execute(base, (attr_filter, category)).fetchall()
                else:
                    # No category filter: match all categories
                    base = "SELECT pattern, attr, note, code, breed, category, l3, tokens FROM breed_spec_rules WHERE attr=?"
                    if breed:
                        sql = base + " AND breed=?"
                        rows = conn.execute(sql, (attr_filter, breed)).fetchall()
                    else:
                        rows = conn.execute(base, (attr_filter,)).fetchall()
            else:
                if category:
                    base = "SELECT pattern, attr, note, code, breed, category, l3, tokens FROM breed_spec_rules WHERE category=?"
                    if breed:
                        sql = base + " AND breed=?"
                        rows = conn.execute(sql, (category, breed)).fetchall()
                    else:
                        rows = conn.execute(base, (category,)).fetchall()
                else:
                    # No category filter: match all categories (skip AND category=? clause)
                    if breed:
                        sql = "SELECT pattern, attr, note, code, breed, category, l3, tokens FROM breed_spec_rules WHERE breed=?"
                        rows = conn.execute(sql, (breed,)).fetchall()
                    else:
                        rows = conn.execute("SELECT pattern, attr, note, code, breed, category, l3, tokens FROM breed_spec_rules").fetchall()

        results = []
        for row in rows:
            rule = self._row_to_rule(row)
            if spec_tokens:
                score = _keyword_score(spec_tokens, rule["tokens"])
                # 降级策略：keyword score >= 0.001 正常保留；
                # score == 0 但 regex 能匹配 spec → 强制加入（解决 Φ HRB 等规则 token 不 overlap 的问题）
                if score < 0.001:
                    # 2026-07-05 优化：用预编译 regex，避免每条规则都重新编译
                    cp = _get_compiled_rule_pattern(rule["pattern"])
                    if cp is None:
                        continue
                    if not cp.search(spec or ""):
                        continue
                    # regex 能匹配但 score 为 0，给一个低分使其排在后面
                    score = 0.0001
            else:
                score = 1.0

            # ═══ l3 / breed / category 加权(v0.7 l3 最高)═══
            # l3 精确匹配 → +0.40(L3 分项,最高优先)
            rule_l3 = (rule.get("l3") or "").strip()
            if l3 and rule_l3 and rule_l3 == l3:
                score += 0.40
            # breed 精确匹配 → +0.30(规则专为该品种设计)
            rule_breed = (rule.get("breed") or "").strip()
            if breed and rule_breed and rule_breed == breed:
                score += 0.30
            # category 精确匹配 → +0.20
            rule_cat = (rule.get("category") or "").strip()
            if category and rule_cat and rule_cat == category:
                score += 0.20

            # ═══ 执行校验 ═══
            if validate_spec is not None:
                code = rule.get("code", "")
                attr = rule.get("attr", "")
                if not self._validate_rule_code(code, validate_spec, attr):
                    continue  # 校验不通过 → 丢弃该规则

            results.append((score, rule))

        results.sort(key=lambda x: x[0], reverse=True)

        # 去重：同 (attr, pattern) 保留最高分
        seen = {}
        deduped = []
        for score, rule in results:
            # Include breed in dedup key so same (attr, pattern) for different breeds are kept
            key = (rule["attr"], rule["pattern"], rule["breed"])
            if key not in seen:
                seen[key] = score
                deduped.append((score, rule))

        return deduped[:top_k]

    def search_by_attr_pattern(self, attr: str, pattern: str) -> dict | None:
        """Exact dedup lookup by attr + pattern (pattern must be normalized)."""
        norm_pat = self._strip_r(pattern)
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT pattern, attr, note, code, breed, category, tokens "
                "FROM breed_spec_rules WHERE attr=? AND pattern=?",
                (attr, norm_pat)
            ).fetchall()
        if rows:
            return self._row_to_rule(rows[0])
        return None

    def rebuild_from_rules_dir(self, rules_dir: str = None) -> int:
        # 默认从仓库 parse_spec/rules 目录重建（备份规则源）
        if rules_dir is None:
            rules_dir = os.path.join(PROJECT_ROOT, "src", "gov_price_etl", "parse_spec", "rules")
        """Rebuild DB from all rules/*.py files. Returns count of rules inserted."""
        import re as _re

        count = 0
        with self._lock:
            conn = sqlite3.connect(self.db_path, timeout=30)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute("DELETE FROM breed_spec_rules")
            conn.commit()

        for py_file in glob.glob(os.path.join(rules_dir, "*.py")):
            if os.path.basename(py_file) in ("vector_store.py", "__init__.py", "_attrs.py"):
                continue
            text = open(py_file, encoding="utf-8").read()

            # ── Parse r'pattern' and r"pattern" ─────────────────────
            pattern_matcher = _re.compile(r"r'([^']*?)(?<!')$|r\"([^\"]*?)(?<!\")$")
            # Sections # ── auto ──
            sections = _re.split(r"\n# ── auto.*?─+\n", text)
            for section in sections[1:]:
                m = _re.match(r"# ── auto.*?─+\s*\n(.*?)", section, _re.DOTALL)
                if not m:
                    continue
                body = m.group(1)
                # Extract attr from comment
                attr_m = _re.search(r"attr[:：]\s*['\"]?(\w+)['\"]?", body)
                if not attr_m:
                    continue
                attr = attr_m.group(1)
                # Extract pattern
                pat_m = _re.search(r"r'([^']*?)'", body)
                if not pat_m:
                    pat_m = _re.search(r'r"([^"]*?)"', body)
                if not pat_m:
                    continue
                pattern = pat_m.group(1)
                # Extract code
                code_m = _re.search(r"(m\s*=\s*re\.search.*?result\[.*?\]\s*=.*?)\s*(?=\n# ──|\Z)", body, _re.DOTALL)
                if not code_m:
                    continue
                code = code_m.group(1).strip()
                note_m = _re.search(r"note[:：]\s*['\"]?([^'\"\n]+)['\"]?", body)
                note = note_m.group(1).strip() if note_m else ""
                breed_m = _re.search(r"breed[:：]\s*['\"]?([^'\"\n]+)['\"]?", body)
                breed = breed_m.group(1).strip() if breed_m else ""
                cat_m = _re.search(r"category[:：]\s*['\"]?([^'\"\n]+)['\"]?", body)
                cat = cat_m.group(1).strip() if cat_m else ""

                self.insert(pattern, attr, note, code, breed, cat, skip_duplicate=True)
                count += 1

        return count

    # ── Utility ────────────────────────────────────────────────────────────

    @staticmethod
    def _strip_r(s: str) -> str:
        """Strip leading r' or r" prefix from a pattern string."""
        s = s.strip()
        if len(s) >= 2 and s[0] in ('r', 'R') and s[1] in ('"', "'"):
            return s[2:-1]
        return s

    def list_rules(self, attr: str = "", limit: int = 100) -> list:
        """Return rule dicts, optionally filtered by attr."""
        with self._lock:
            conn = self._get_conn()
            if attr:
                rows = conn.execute(
                    "SELECT pattern, attr, note, code, breed, category, tokens "
                    "FROM breed_spec_rules WHERE attr=? LIMIT ?",
                    (attr, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT pattern, attr, note, code, breed, category, tokens "
                    "FROM breed_spec_rules LIMIT ?",
                    (limit,)
                ).fetchall()
        return [self._row_to_rule(r) for r in rows]

    def clear(self) -> None:
        with self._lock:
            conn = sqlite3.connect(self.db_path, timeout=30)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute("DELETE FROM breed_spec_rules")
            conn.commit()
            conn.close()


# ── Module-level singleton ───────────────────────────────────────────────────

_store = None
_lock  = threading.Lock()


def get_vec_store() -> VecStore:
    global _store
    if _store is None:
        with _lock:
            if _store is None:
                _store = VecStore()
    return _store


def rebuild_vec_db() -> int:
    """Rebuild the vector DB from rules/*.py files. Returns count."""
    vs = get_vec_store()
    vs.clear()
    return vs.rebuild_from_rules_dir()


if __name__ == "__main__":
    import sys
    vs = VecStore()
    if len(sys.argv) > 1 and sys.argv[1] == "rebuild":
        count = vs.rebuild_from_rules_dir()
        print(f"Rebuilt {count} rules")
    else:
        print(f"VecStore ready: {vs.db_path}")

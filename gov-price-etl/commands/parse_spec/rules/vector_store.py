#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parse_spec/rules/vector_store.py
Rule vector store with SQLite + blob persistence.
Primary: keyword-set similarity (no external dependency).
Fallback: Ollama local embedding when available.
"""
import json, os, re, glob, threading, math
import numpy as np
import sqlite3

RULES_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(RULES_DIR, "rules_vec.db")

OLLAMA_BASE = "http://localhost:11434"
OLLAMA_MODEL = "nomic-embed-text"


# ── Embedding: keyword-set similarity (primary, zero-dep) ────────────────────

KEYWORD_STOPWORDS = frozenset([
    "a", "an", "the", "for", "of", "in", "on", "at", "to", "with",
    "and", "or", "is", "was", "are", "been", "be", "as", "by", "from",
    "规则", "pattern", "attr", "用于", "rule",
])

def _tokenize(text: str) -> set:
    tokens = set()
    for token in re.split(r'[^a-zA-Z0-9\u4e00-\u9fff]+', text.lower()):
        if token and token not in KEYWORD_STOPWORDS and len(token) > 1:
            tokens.add(token)
    return tokens

def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0

def _keyword_score(spec_tokens: set, rule_tokens: set) -> float:
    return _jaccard(spec_tokens, rule_tokens)

def _embed_text(text: str) -> np.ndarray:
    """Compute fake embedding via keyword-set hash (primary, no external dep)."""
    tokens = _tokenize(text)
    dim = 256
    vec = np.zeros(dim, dtype=np.float32)
    for i, tok in enumerate(tokens):
        h = hash(tok) % dim
        vec[h] += 1.0
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec


# ── Vector Store ─────────────────────────────────────────────────────────────

def get_vec_store(db_path: str = DB_PATH) -> RuleVectorStore:
    return RuleVectorStore.get_vec_store(db_path)


class RuleVectorStore:
    _instance = None
    _lock = threading.Lock()

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._ensure_db()

    @classmethod
    def get_vec_store(cls, db_path: str = DB_PATH) -> "RuleVectorStore":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(db_path)
        return cls._instance

    def _ensure_db(self):
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS rule_vectors (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern     TEXT    NOT NULL,
                    attr        TEXT    NOT NULL,
                    note        TEXT,
                    code        TEXT,
                    breed       TEXT,
                    category    TEXT,
                    tokens      TEXT,   -- JSON serialized keyword set
                    embedding   BLOB,   -- float32 vector blob
                    created_at  TEXT    DEFAULT (datetime('now'))
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_attr ON rule_vectors(attr)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_category ON rule_vectors(category)")
            conn.commit()
            conn.close()

    def _strip_r(self, s):
        """Strip python r'...' or r"..." raw string wrapper.
        Handles malformed cases: r'..." (closing " from JSON) or missing closing quote.
        """
        if not s:
            return s or ""
        s = s.strip()
        if len(s) < 4:
            return s
        if s.startswith('r"') and s.endswith('"') and len(s) > 2:
            return s[2:-1]
        if s.startswith("r'"):
            for i in range(2, len(s)):
                if s[i] == "'" and (i == 0 or s[i-1] != '\\'):
                    return s[2:i]
            last_single = -1
            for i in range(len(s) - 1, 1, -1):
                if s[i] == "'" and (i == 0 or s[i-1] != '\\'):
                    last_single = i
                    break
            if last_single > 2:
                return s[2:last_single]
            return s[2:]
        return s

    def _row_to_rule(self, row: tuple) -> dict:
        _, pattern, attr, note, code, breed, category, tokens_json, embedding_bytes, created_at = row
        pattern = self._strip_r(pattern)
        code = self._strip_r(code)
        rule = {
            "pattern":  pattern,
            "attr":     attr,
            "note":     note or "",
            "code":     code or "",
            "breed":    breed or "",
            "category": category or "",
            "tokens":   set(json.loads(tokens_json)) if tokens_json else set(),
            "embedding": np.frombuffer(embedding_bytes, dtype=np.float32) if embedding_bytes else None,
            "created_at": created_at,
        }
        return rule

    def insert(self, pattern: str, attr: str, note: str,
               code: str, breed: str = "", category: str = "",
               skip_duplicate: bool = True) -> bool:
        """
        Insert rule with token set + embedding. Returns True if inserted.
        Pattern and code stored normalized (strip r'...' wrapper).
        skip_duplicate: check normalized (attr, pattern) existence.
        """
        norm_pat = self._strip_r(pattern)
        norm_code = self._strip_r(code)
        if skip_duplicate and self.search_by_attr_pattern(attr, norm_pat):
            return False

        text_parts = [spec for spec in [attr, note, breed, category] if spec]
        text = " ".join(text_parts) + " " + norm_pat
        tokens = _tokenize(text)
        embedding = _embed_text(text)
        embedding_bytes = embedding.tobytes()

        tokens_json = json.dumps(list(tokens))

        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute("""
                INSERT INTO rule_vectors (pattern, attr, note, code, breed, category, tokens, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (norm_pat, attr, note, norm_code, breed, category, tokens_json, embedding_bytes))
            conn.commit()
            conn.close()

        return True

    def search(self, spec: str = "", category: str = "", breed: str = "",
               top_k: int = 8, attr_filter: str = "") -> list:
        """
        Keyword similarity search (primary, no external dep).
        Returns sorted list of (score, rule_dict).
        Deduplicates by (attr, pattern) keeping highest score.
        """
        spec_tokens = _tokenize(spec or "")
        results = []

        with self._lock:
            conn = sqlite3.connect(self.db_path)
            if attr_filter:
                rows = conn.execute(
                    "SELECT * FROM rule_vectors WHERE attr=?",
                    (attr_filter,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM rule_vectors").fetchall()
            conn.close()

        for row in rows:
            rule = self._row_to_rule(row)
            if spec_tokens:
                score = _keyword_score(spec_tokens, rule["tokens"])
                if score <= 0:
                    continue
            else:
                score = 1.0
            results.append((score, rule))

        results.sort(key=lambda x: x[0], reverse=True)

        # Deduplicate by (attr, pattern) - keep highest score
        seen = {}
        deduped = []
        for score, rule in results:
            key = (rule["attr"], rule["pattern"])
            if key not in seen:
                seen[key] = score
                deduped.append((score, rule))

        return deduped[:top_k]

    def search_by_attr_pattern(self, attr: str, pattern: str) -> dict | None:
        """Exact dedup lookup by attr + pattern (pattern must be normalized)."""
        norm_pat = self._strip_r(pattern)
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            rows = conn.execute(
                "SELECT * FROM rule_vectors WHERE attr=? AND pattern=?",
                (attr, norm_pat)
            ).fetchall()
            conn.close()
        if rows:
            _, _, _, _, _, _, _, _, _, _ = rows[0]
            return self._row_to_rule(rows[0])
        return None

    def rebuild_from_rules_dir(self, rules_dir: str = RULES_DIR) -> int:
        """Rebuild DB from all rules/*.py files. Returns count of rules inserted."""
        import re as _re

        count = 0
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute("DELETE FROM rule_vectors")
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

    def count(self) -> int:
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            n = conn.execute("SELECT COUNT(*) FROM rule_vectors").fetchone()[0]
            conn.close()
            return n

    def clear(self):
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute("DELETE FROM rule_vectors")
            conn.commit()
            conn.close()
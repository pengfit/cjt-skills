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
    """Split on non-alphanumeric, lowercase, remove stopwords."""
    tokens = set()
    for token in re.split(r'[^a-zA-Z0-9\u4e00-\u9fff]+', text.lower()):
        if token and token not in KEYWORD_STOPWORDS and len(token) > 1:
            tokens.add(token)
    return tokens


def _keyword_embedding(text: str, dim: int = 256) -> np.ndarray:
    """
    Convert text to a dense pseudo-vector via keyword set.
    Creates a dim维 vector from token hash buckets.
    """
    tokens = _tokenize(text)
    vec = np.zeros(dim, dtype=np.float32)
    for token in tokens:
        h = int(hash(token)) % dim
        vec[h] += 1.0
    # Normalize
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec


def _jaccard_sim(set_a: set, set_b: set) -> float:
    if not set_a or not set_b:
        return 0.0
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    return inter / union if union > 0 else 0.0


# ── Ollama embedding (fallback) ─────────────────────────────────────────────

def _embed_text_via_ollama(text: str) -> np.ndarray | None:
    """Try Ollama. Returns None on failure (caller falls back to keyword vec)."""
    import urllib.request

    body = json.dumps({
        "model": OLLAMA_MODEL,
        "input": text,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/embeddings",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            emb = result.get("embeddings", [])
            if emb:
                return np.array(emb, dtype=np.float32)
    except Exception:
        pass
    return None


def _embed_text(text: str) -> np.ndarray:
    """
    Unified entry: try Ollama first, fall back to keyword embedding.
    Returns normalized vector.
    """
    vec = _embed_text_via_ollama(text)
    if vec is not None and np.any(vec != 0):
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec
    # Fallback: keyword pseudo-embedding
    vec = _keyword_embedding(text, dim=256)
    return vec


# ── Similarity ────────────────────────────────────────────────────────────────

def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / norm) if norm > 0 else 0.0


# ── RuleVectorStore ────────────────────────────────────────────────────────────

class RuleVectorStore:
    """
    Append-only rule vector store backed by SQLite + blob.
    Stores both keyword-set tokens (for jaccard search) and embedding blob.
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._ensure_db()

    def _ensure_db(self):
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS rule_vectors (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern    TEXT    NOT NULL,
                    attr       TEXT    NOT NULL,
                    note       TEXT,
                    code       TEXT,
                    breed      TEXT,
                    category   TEXT,
                    tokens     TEXT,   -- JSON serialized keyword set
                    embedding  BLOB,   -- float32 vector blob
                    created_at TEXT    DEFAULT (datetime('now'))
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_attr ON rule_vectors(attr)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_category ON rule_vectors(category)")
            conn.commit()
            conn.close()

    def _row_to_rule(self, row: tuple) -> dict:
        _, pattern, attr, note, code, breed, category, tokens_json, embedding_bytes, created_at = row
        rule = {
            "pattern":  pattern,
            "attr":     attr,
            "note":     note or "",
            "code":     code or "",
            "breed":    breed or "",
            "category": category or "",
            "tokens":   json.loads(tokens_json) if tokens_json else set(),
            "embedding": np.frombuffer(embedding_bytes, dtype=np.float32) if embedding_bytes else None,
            "created_at": created_at,
        }
        return rule

    def insert(self, pattern: str, attr: str, note: str,
               code: str, breed: str = "", category: str = "",
               skip_duplicate: bool = True) -> bool:
        """
        Insert rule with token set + embedding. Returns True if inserted.
        skip_duplicate: check attr+pattern existence.
        """
        if skip_duplicate and self.search_by_attr_pattern(attr, pattern):
            return False

        # Build text for embedding
        text_parts = [spec for spec in [attr, note, breed, category] if spec]
        text = " ".join(text_parts) + " " + pattern
        tokens = _tokenize(text)
        embedding = _embed_text(text)
        embedding_bytes = embedding.tobytes()

        tokens_json = json.dumps(list(tokens))

        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.execute("""
                INSERT INTO rule_vectors (pattern, attr, note, code, breed, category, tokens, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (pattern, attr, note, code, breed, category, tokens_json, embedding_bytes))
            conn.commit()
            conn.close()

        return True

    def search(self, spec: str = "", category: str = "", breed: str = "",
               top_k: int = 8, attr_filter: str = "") -> list:
        """
        Semantic search combining cosine similarity (embedding) + jaccard (tokens).
        Returns: [(combined_score, rule_dict), ...]
        """
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM rule_vectors").fetchall()
            conn.close()

        if not rows:
            return []

        query_text = " ".join(p for p in [spec, category, breed] if p)
        query_tokens = _tokenize(query_text)
        query_embedding = _embed_text(query_text)

        scored = []
        for row in rows:
            rule = self._row_to_rule(tuple(row))
            if attr_filter and rule["attr"] != attr_filter:
                continue

            # Embedding cosine similarity
            emb_sim = 0.0
            if rule["embedding"] is not None:
                emb_sim = _cosine_sim(query_embedding, rule["embedding"])

            # Token Jaccard similarity
            tok_sim = _jaccard_sim(query_tokens, set(rule["tokens"]))

            # Combined score (weighted average)
            combined = 0.6 * emb_sim + 0.4 * tok_sim

            scored.append((combined, rule))

        scored.sort(key=lambda x: -x[0])
        return scored[:top_k]

    def search_by_attr_pattern(self, attr: str, pattern: str) -> dict | None:
        """Exact dedup lookup by attr + pattern."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute("""
                SELECT * FROM rule_vectors
                WHERE attr = ? AND pattern = ?
                LIMIT 1
            """, (attr, pattern)).fetchone()
            conn.close()

        if row:
            return self._row_to_rule(tuple(row))
        return None

    def rebuild_from_rules_dir(self, rules_dir: str = RULES_DIR) -> int:
        """
        Migrate all rules from rules/*.py into vector DB.
        Returns count of newly inserted rules.
        """
        pattern_re = re.compile(
            r'# ── 自动生成: (.+?) ──\s*\n(.*?)(?=\n# ──|\Z)',
            re.DOTALL,
        )

        count = 0
        for py_file in glob.glob(os.path.join(rules_dir, "*.py")):
            basename = os.path.basename(py_file)
            if basename in ("__init__.py", "_attrs.py"):
                continue
            attr = basename[:-3]
            with open(py_file) as f:
                content = f.read()

            for m in pattern_re.finditer(content):
                note = m.group(1).strip()
                code = m.group(2).strip()
                pat_m = re.search(r"re\.search\(r['\"]([^'\"]+)['\"]", code)
                if not pat_m:
                    continue
                pattern = pat_m.group(1)
                ok = self.insert(pattern, attr, note, code,
                                 breed="", category="", skip_duplicate=True)
                if ok:
                    count += 1

        return count


# ── Singleton ──────────────────────────────────────────────────────────────────
_vec_store = None


def get_vec_store() -> RuleVectorStore:
    global _vec_store
    if _vec_store is None:
        _vec_store = RuleVectorStore()
    return _vec_store


if __name__ == "__main__":
    vs = get_vec_store()
    n = vs.rebuild_from_rules_dir()
    print(f"[vector_store] migrated {n} rules")
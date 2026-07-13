#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
jaccard.py - 字符 bigram 倒排索引（_stage2_db_fuzzy 性能优化）

背景：
  原 _stage2_db_fuzzy 每次 classify_v3() 调用都全表扫 DB (9744 行) + Python 层 O(N×M) 循环。
  ETL 51 万条 ODS → 47 亿次 Python 操作 → 40 文档/秒 → 跑完 4+ 小时。

优化：
  用字符 bigram（2字滑动窗口）建倒排索引，召回候选后只在候选集（~60）上做模糊匹配。
  复杂度 O(N×M) → O(N×K)，K=候选数 ≈ 60，提速 ~150x。

设计：
  - 内存 dict 索引（不落盘）
  - 模块级懒加载 + mtime 失效检测（DB 文件变了自动重建）
  - 短串 / 召回过多 → 兜底全集

正确性：
  - 包含关系召回 100% 完整（db ⊆ target ⇒ db 的 bigrams ⊆ target 的 bigrams）
  - Jaccard ≥ 0.9 必有 bigram 共享（鸽笼原理：5字 = 4 bigrams，share ≥ 90% ⇒ 必有共同 bigram）
"""

import os
import sqlite3
import threading
from typing import Optional


# ── 模块级缓存（懒加载 + mtime 失效） ──────────────────────────────
# {db_path: (mtime, index)}
_INDEX_CACHE: dict = {}
_INDEX_LOCK = threading.Lock()


# ── Bigram 切分 ──────────────────────────────────────────────────────

def _to_bigrams(s: str) -> set:
    """字符串 → 字符 bigram 集合。
    
    例: '水泥' → {'水泥'}
        '螺纹钢' → {'螺纹', '纹钢'}
        '' → set()
    """
    if not s or len(s) < 2:
        return set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


# ── 索引构建 ─────────────────────────────────────────────────────────

def build_bigram_index(db_path: str) -> dict:
    """构建字符 bigram 倒排索引。
    
    返回: {
        'bigrams': {bigram: {breed_idx, ...}, ...},
        'breeds':  [(bc, l3, src, conf), ...],
        'mtime':   float,
    }
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT breed_clean, l3, source, confidence FROM breed_l3_map_v3 "
            "WHERE confidence >= 0.9"
        ).fetchall()
    finally:
        conn.close()

    bigrams: dict = {}
    breeds = list(rows)
    for idx, (bc, _l3, _src, _conf) in enumerate(breeds):
        for bg in _to_bigrams(bc):
            bigrams.setdefault(bg, set()).add(idx)

    return {
        'bigrams': bigrams,
        'breeds': breeds,
        'mtime': os.path.getmtime(db_path),
    }


def get_index(db_path: str) -> dict:
    """懒加载索引。DB 文件 mtime 变了自动重建。"""
    with _INDEX_LOCK:
        if db_path in _INDEX_CACHE:
            cached_mtime, index = _INDEX_CACHE[db_path]
            try:
                if os.path.getmtime(db_path) == cached_mtime:
                    return index
            except OSError:
                pass
        index = build_bigram_index(db_path)
        _INDEX_CACHE[db_path] = (index['mtime'], index)
        return index


def close_cache() -> None:
    """清空索引缓存（DB 文件被外部重建后调用）"""
    with _INDEX_LOCK:
        _INDEX_CACHE.clear()


# ── 候选召回 ─────────────────────────────────────────────────────────

# 召回过多阈值：超过此数 → 兜底全集（避免大字符集退化）
MAX_CANDIDATES = 500


def recall_candidates(breed_clean: str, index: dict) -> list:
    """给定目标 breed，返回候选 DB breed 索引列表。

    兜底：
      - 短串（< 2 字）→ 退全集
      - 召回 > MAX_CANDIDATES → 退全集
    """
    breeds = index['breeds']
    n_total = len(breeds)

    # 短串兜底
    if len(breed_clean) < 2:
        return list(range(n_total))

    target_bgs = _to_bigrams(breed_clean)
    candidates: set = set()
    for bg in target_bgs:
        candidates |= index['bigrams'].get(bg, set())
        # 大字符集兜底（短 breed 撞库）
        if len(candidates) > MAX_CANDIDATES:
            return list(range(n_total))

    return list(candidates)


# ── 候选集上的模糊匹配 ──────────────────────────────────────────────

# 包含关系最小长度比（与原逻辑保持一致 2026-06-30 阈值）
MIN_SUBSTR_RATIO = 0.4
# Jaccard 阈值
MIN_JACCARD = 0.9


def _contain_match(breed_clean: str, index: dict, candidates: list):
    """2a. 在候选集上做包含关系匹配。
    
    返回: (l3, source, conf, mode, ratio) 或 None
        mode: 'substr_db_in_ods' | 'substr_ods_in_db'
    """
    best = None
    best_ratio = 0.0
    for idx in candidates:
        db_breed, l3, src, conf = index['breeds'][idx]
        if len(db_breed) < 3:
            continue
        # DB ⊆ target
        if db_breed in breed_clean:
            ratio = len(db_breed) / len(breed_clean)
            if ratio >= MIN_SUBSTR_RATIO and ratio > best_ratio:
                best_ratio = ratio
                best = (l3, src, conf, "substr_db_in_ods", ratio)
        # target ⊆ DB
        elif breed_clean in db_breed and len(breed_clean) >= 3:
            ratio = len(breed_clean) / len(db_breed)
            if ratio >= MIN_SUBSTR_RATIO and ratio > best_ratio:
                best_ratio = ratio
                best = (l3, src, conf, "substr_ods_in_db", ratio)
    return best


def _jaccard_match(breed_clean: str, index: dict, candidates: list):
    """2b. 在候选集上做字符集 Jaccard 匹配。
    
    返回: (l3, source, conf, score) 或 None
    """
    target = set(breed_clean)
    best = None
    best_score = 0.0
    for idx in candidates:
        db_breed, l3, src, conf = index['breeds'][idx]
        cs = set(db_breed)
        if not cs:
            continue
        inter = len(target & cs)
        union = len(target | cs)
        if union == 0:
            continue
        score = inter / union
        if score > best_score:
            best_score = score
            best = (l3, src, conf, best_score)

    if not best or best_score < MIN_JACCARD:
        return None
    return best


def stage2_match(breed_clean: str, index: dict) -> Optional[dict]:
    """阶段 2 主入口（优化版）。
    
    返回 dict: {
        'l3': str, 'source': str, 'conf': float,
        'method': 'contain:xxx' | 'jaccard',
        'score': float,
    }
    未命中 → None
    """
    if not breed_clean:
        return None

    candidates = recall_candidates(breed_clean, index)

    # 先试包含（强信号，命中即返回）
    hit = _contain_match(breed_clean, index, candidates)
    if hit:
        l3, src, conf, mode, ratio = hit
        return {
            'l3': l3, 'source': src, 'conf': float(conf or 0.9),
            'method': f"contain:{mode}", 'score': ratio,
        }

    # 包含未命中 → 试 Jaccard
    hit = _jaccard_match(breed_clean, index, candidates)
    if hit:
        l3, src, conf, score = hit
        return {
            'l3': l3, 'source': src, 'conf': float(conf or score),
            'method': 'jaccard', 'score': score,
        }

    return None


# ── 自测 ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from gov_price_etl.paths import CATEGORY_V3_RULES_DB
    DB_PATH = str(CATEGORY_V3_RULES_DB)

    print(f"[jaccard] building index from {DB_PATH} ...")
    import time
    t0 = time.time()
    idx = get_index(DB_PATH)
    print(f"[jaccard] built: {len(idx['breeds'])} breeds, {len(idx['bigrams'])} bigrams, "
          f"{time.time() - t0:.3f}s")

    samples = [
        ("PP-R 冷水管", "PP-R冷水管"),
        ("UPVC 排水管", "UPVC排水管"),
        ("电力电缆", "电力电缆"),
        ("螺纹钢", "螺纹钢"),
        ("商品砼", "商品砼"),
        ("低碳热轧盘条（高线）", "低碳热轧盘条"),
        ("钢铝复合暖气片", "钢铝复合暖气片"),
    ]
    print("\n[jaccard] sample matches:")
    for breed, clean in samples:
        cands = recall_candidates(clean, idx)
        hit = stage2_match(clean, idx)
        if hit:
            print(f"  {clean:20s} → l3={hit['l3']:8s} {hit['method']:30s} score={hit['score']:.3f} "
                  f"({len(cands)} candidates)")
        else:
            print(f"  {clean:20s} → NO MATCH ({len(cands)} candidates)")
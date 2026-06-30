#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
category_v3.py - 4 层分类主入口（5 段式，v3 DB）

2 段式（每条数据依次走 2 段，命中即返回）：
  1. db_exact_v3     breed_l3_map_v3 表精确匹配（confidence >= 0.9）
  2. db_fuzzy_v3     包含关系 + Jaccard 模糊召回（TOP 1，confidence >= 0.9）
     - 2026-06-30 增强：包含关系长度比 0.5 → 0.45，解除 PP-R/PE-RT 全局 deny
     - 配套：clean_breed 加全角括号→半角、Mpa→MPa 规范化

未命中 → 返回 no_match_v3（不写 DWD，等 breed 补入缓存后重跑）
"""

import sqlite3
import threading
from pathlib import Path
from typing import Optional


# ── 路径（与现有 ETL 一致） ─────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB_PATH = DATA_DIR / "category_v3_rules.db"


# ── 模块级 SQLite 连接单例（性能优化） ──────────────────────────────
# 背景：ETL 一轮 150K 条记录，classify_v2 被调 150K 次。
#       每次新建 sqlite3.connect + HEAD/INDEX 加载~5ms，150K 次 = 12 分钟。
# 优化：进程级单例连接（read-only + 线程锁），
#       首次调用打开，后续复用 ~0.05ms/次。
_DB_SINGLETON: dict = {}  # {db_path: Connection}
_DB_LOCK = threading.Lock()


def _get_singleton_conn(db_path: str) -> sqlite3.Connection:
    """取（懒加载）单例 SQLite 连接。线程安全。"""
    if db_path in _DB_SINGLETON:
        return _DB_SINGLETON[db_path]
    with _DB_LOCK:
        # 二次检查（其他线程可能已加进）
        if db_path in _DB_SINGLETON:
            return _DB_SINGLETON[db_path]
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
        _DB_SINGLETON[db_path] = conn
        return conn


def close_singleton() -> None:
    """进程退出时调用（其他地方也可能会调）。"""
    with _DB_LOCK:
        for conn in _DB_SINGLETON.values():
            try:
                conn.close()
            except Exception:
                pass
        _DB_SINGLETON.clear()


# ── 工具函数 ───────────────────────────────────────────────────────────

def _open_db(db_path: Optional[str] = None) -> sqlite3.Connection:
    """打开 SQLite 库连接（read-only intent）

    默认走模块级单例（性能优化）。测试或特定场景可用 _open_db_fresh() 拿独立连接。
    """
    path = db_path or str(DEFAULT_DB_PATH)
    return _get_singleton_conn(path)


def _open_db_fresh(db_path: Optional[str] = None) -> sqlite3.Connection:
    """新开一个独立连接（不走单例）。用于测试或需要写时拿独立连接的场合。"""
    path = db_path or str(DEFAULT_DB_PATH)
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _is_conn_alive(conn: sqlite3.Connection) -> bool:
    """检查 sqlite 连接是否还活着（未 close）"""
    try:
        conn.execute("SELECT 1").fetchone()
        return True
    except Exception:
        return False


def _ensure_alive_conn(db_path: str) -> sqlite3.Connection:
    """拿单例连接，如果已死/被 close/文件被删，丢单例重开。"""
    conn = _get_singleton_conn(db_path)
    if not _is_conn_alive(conn):
        # 重置该 path 的单例
        with _DB_LOCK:
            if db_path in _DB_SINGLETON:
                try:
                    _DB_SINGLETON[db_path].close()
                except Exception:
                    pass
                del _DB_SINGLETON[db_path]
        return _get_singleton_conn(db_path)
    return conn


def _load_category_node(conn: sqlite3.Connection, l3: str) -> Optional[dict]:
    """根据 L3 码查 category_v3 表完整节点"""
    row = conn.execute(
        """SELECT l1, l2, l3, l4, gb_50500, ifc_class, uniclass_ss,
                  eng_part, eng_stage, main_or_aux, unit, billing_unit,
                  cost_method, name_l1, name_l2, name_l3
           FROM category_v3 WHERE l3 = ? LIMIT 1""",
        (l3,),
    ).fetchone()
    if not row:
        return None
    return {
        "l1": row[0], "l2": row[1], "l3": row[2], "l4": row[3],
        "gb_50500": row[4], "ifc_class": row[5],
        "uniclass_ss": row[6], "eng_part": row[7], "eng_stage": row[8],
        "main_or_aux": row[9], "unit": row[10], "billing_unit": row[11],
        "cost_method": row[12], "name_l1": row[13], "name_l2": row[14],
        "name_l3": row[15],
    }


def _format_result(node: dict, source: str, confidence: float, fuzzy_match: bool = False,
                   fuzzy_method: str = "", fuzzy_score: float = 0.0) -> dict:
    """把 DB 节点 + 来源 + 置信度打包成 v2 分类结果"""
    result = {
        "l1": node.get("l1", ""),
        "l2": node.get("l2", ""),
        "l3": node.get("l3", ""),
        "l4": node.get("l4", "UNCLASSIFIED"),
        "gb_50500":   node.get("gb_50500"),
        "quota_ref":  node.get("quota_ref"),
        "ifc_class":  node.get("ifc_class"),
        "uniclass_ss": node.get("uniclass_ss"),
        "eng_part":   node.get("eng_part"),
        "eng_stage":  node.get("eng_stage"),
        "main_or_aux": node.get("main_or_aux"),
        "unit":       node.get("unit"),
        "billing_unit": node.get("billing_unit"),
        "cost_method": node.get("cost_method"),
        "name_l1":    node.get("name_l1", ""),
        "name_l2":    node.get("name_l2", ""),
        "name_l3":    node.get("name_l3", ""),
        "category_v2_source": source,
        "category_v2_confidence": confidence,
    }
    if fuzzy_match:
        result["fuzzy_match"] = True
        result["fuzzy_method"] = fuzzy_method
        result["fuzzy_score"] = fuzzy_score
    return result


# ── 2 段式 ─────────────────────────────────────────────────────────────

def _stage1_db_exact(conn: sqlite3.Connection, breed_clean: str) -> Optional[dict]:
    """阶段 1: breed_l3_map_v3 表精确匹配（仅 conf >= MIN_RULE_CONFIDENCE 视为有效）"""
    if not breed_clean:
        return None
    from gov_price_etl.classify.constants import MIN_RULE_CONFIDENCE
    row = conn.execute(
        "SELECT l3, source, confidence FROM breed_l3_map_v3 "
        "WHERE breed_clean = ? AND confidence >= ? LIMIT 1",
        (breed_clean, MIN_RULE_CONFIDENCE),
    ).fetchone()
    if not row:
        return None
    l3, source, conf = row
    node = _load_category_node(conn, l3)
    if not node:
        return None
    return _format_result(node, "db_exact_v3", float(conf or 1.0))


def _stage2_db_fuzzy(conn: sqlite3.Connection, breed_clean: str) -> Optional[dict]:
    """阶段 2: 模糊召回（TOP 1，confidence >= 0.9）

    2 个子阶段，命中即返回：
      2a. 包含关系快速匹配：DB breed 是 ODS breed 的子串（或反之），长度比 >= 0.4
          - 强信号：能召回「低碳热轧盘条（高线） → 低碳热轧盘条」「钢铝复合暖气片 → 钢铝复合暖气片670*50*100」
          - 2026-06-30: ratio 0.5 → 0.4（多召 ~6000 条 ODS）
          - 2026-06-30: 解除 PP-R/PE-RT 全局 deny（DB 中 PE-RT 仅 1 条，PB 9 条多是 HPB300 误匹配，真实风险极低）
      2b. 字符集 Jaccard（>= 0.9）：弱信号，对长尾命名召回率低
    """
    if not breed_clean:
        return None
    from gov_price_etl.classify.constants import MIN_RULE_CONFIDENCE

    # 候选集：DB 中 confidence >= MIN_RULE_CONFIDENCE 的项
    rows = conn.execute(
        "SELECT breed_clean, l3, source, confidence FROM breed_l3_map_v3 "
        "WHERE confidence >= ?",
        (MIN_RULE_CONFIDENCE,),
    ).fetchall()
    if not rows:
        return None

    # ── 2a. 包含关系快速匹配（强信号）──
    # 条件：DB breed 是 ODS breed 的子串（或反之），且长度比 >= MIN_SUBSTR_RATIO
    # 2026-06-30: 取消 PP-R/PE-RT 全局 deny。
    # 理由：DB 中 PE-RT 仅 1 条 (PE-RT复合管→03.01.03)，PERT 1 条 (PERT耐热聚乙烯地暖盘管De20→05.03.02)，
    #       真实 PB管 几乎为 0（LIKE '%PB%' 抓到的 9 条全是 HPB300 钢筋，钢筋是 HPB 字符前缀）。
    #       PP-R 误分到 PE-RT 风险极低；且即使误分，PP-R 和 PE-RT 在 DB 中都映射到 03.01.x（给水管），最终 L3 一致。
    # 阈值 0.4 vs 0.5: 0.5 太严,丢失「钢铝复合暖气片 → 钢铝复合暖气片670*50*100」(ratio 0.41) 等大量高置信召回。
    # 短串保护：DB breed 长度 < 3 直接 skip,防止"水泥"/"砂"等过短字符串乱匹配。
    MIN_SUBSTR_RATIO = 0.4
    best_sub = None
    best_sub_len_ratio = 0.0
    for db_breed, l3, source, conf in rows:
        if len(db_breed) < 3:
            continue
        # ODS breed 是 DB breed 的子串（ODS 是 DB 的子集/更细）
        if db_breed in breed_clean:
            ratio = len(db_breed) / len(breed_clean)
            if ratio >= MIN_SUBSTR_RATIO and ratio > best_sub_len_ratio:
                best_sub_len_ratio = ratio
                best_sub = (l3, source, conf, "substr_db_in_ods", ratio)
        # DB breed 是 ODS breed 的子串（DB 是 ODS 的子集/更细）
        elif breed_clean in db_breed and len(breed_clean) >= 3:
            ratio = len(breed_clean) / len(db_breed)
            if ratio >= MIN_SUBSTR_RATIO and ratio > best_sub_len_ratio:
                best_sub_len_ratio = ratio
                best_sub = (l3, source, conf, "substr_ods_in_db", ratio)
    if best_sub:
        l3, source, conf, mode, ratio = best_sub
        node = _load_category_node(conn, l3)
        if node:
            return _format_result(
                node, "db_fuzzy_v3", float(conf or 0.9), fuzzy_match=True,
                fuzzy_method=f"contain:{mode}", fuzzy_score=round(ratio, 3),
            )

    # ── 2b. 字符集 Jaccard（弱信号）──
    target = set(breed_clean)
    best = None
    best_score = 0.0
    for db_breed, l3, source, conf in rows:
        candidate = set(db_breed)
        if not candidate:
            continue
        inter = len(target & candidate)
        union = len(target | candidate)
        if union == 0:
            continue
        score = inter / union
        if score > best_score:
            best_score = score
            best = (l3, source, conf)

    if not best or best_score < 0.9:
        return None
    l3, source, conf = best
    node = _load_category_node(conn, l3)
    if not node:
        return None
    return _format_result(
        node, "db_fuzzy_v3", round(best_score, 3), fuzzy_match=True,
        fuzzy_method="jaccard", fuzzy_score=round(best_score, 3),
    )




# ── 主入口 ─────────────────────────────────────────────────────────────

def classify_v3(
    breed: str,
    spec: str,
    unit: str,
    breed_clean: str,
    db_path: Optional[str] = None,
) -> dict:
    """
    4 层分类主入口（2 段式）。
    返回结构化结果，category_v2_source 标识命中段。
    未命中 → no_match_v3，不写 DWD。
    """
    try:
        path = db_path or str(DEFAULT_DB_PATH)
        # 拿一个保证活着的连接（自动重连，健壮）
        conn = _ensure_alive_conn(path)
        # 注意：不用 try/finally conn.close()——这是单例，进程退出才关
        for stage_fn in (
            lambda: _stage1_db_exact(conn, breed_clean),
            lambda: _stage2_db_fuzzy(conn, breed_clean),
        ):
            hit = stage_fn()
            if hit is not None:
                return hit
        # 未命中 → 返回 no_match_v3（不写 DWD）
        return _format_result(
            {"l1": "", "l2": "", "l3": "", "l4": "UNCLASSIFIED",
             "name_l1": "", "name_l2": "", "name_l3": ""},
            "no_match_v3", 0.0,
        )
    except Exception as e:
        # fail-safe：库文件不存在等异常 → 返回空结果
        return {
            "l1": "", "l2": "", "l3": "", "l4": "UNCLASSIFIED",
            "category_v2_source": "error_v3",
            "category_v2_confidence": 0.0,
            "error": str(e),
        }


if __name__ == "__main__":
    # 简单自测
    samples = [
        ("PP-R 冷水管", "DN25 1.6MPa", "m", "PP-R冷水管"),
        ("UPVC 排水管", "DN100", "m", "UPVC排水管"),
        ("电力电缆", "YJV 4×185", "m", "电力电缆"),
        ("螺纹钢", "HRB400 Φ20", "t", "螺纹钢"),
        ("商品砼", "C30", "m³", "商品砼"),
    ]
    for breed, spec, unit, clean in samples:
        r = classify_v2(breed, spec, unit, clean)
        print(f"  {breed:15s} | {spec:20s} | {unit:3s} → L3={r['l3']:8s} {r['category_v2_source']:15s} conf={r['category_v2_confidence']}")

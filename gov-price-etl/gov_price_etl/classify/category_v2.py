#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
category_v2.py - 4 层分类主入口（5 段式）

调用方式：
    from gov_price_etl.classify.category_v2 import classify_v2
    result = classify_v2(
        breed="PP-R 冷水管",
        spec="DN25 1.6MPa",
        unit="m",
        breed_clean="PP-R冷水管",
    )
    # → {"l1": "03", "l2": "03.01", "l3": "03.01.02", "l4": "UNCLASSIFIED",
    #    "gb_50500": "031002", "ifc_class": "IfcPipeSegment",
    #    "eng_part": "安装", "eng_stage": "设计,施工,运维",
    #    "main_or_aux": "主材", "unit": "m", "billing_unit": "m",
    #    "cost_method": "清单+定额", "category_v2_source": "pattern_v2"}

5 段式（每条数据依次走 5 段，命中即返回）：
  1. db_exact_v2     breed_l3_map 表精确匹配
  2. db_fuzzy_v2     Jaccard 模糊召回（TOP 1，confidence >= 0.6）
  3. pattern_v2      L4 patterns 规则（spec 正则 → L3 推断）
  4. ai_v2           AI 分类（结构化输出 L1-L3 + 9 字段）—— 串行批次
  5. fallback_v2     unit 兜底（基于 unit 推断 L3）

设计原则：
  - 阶段 1-3 不调 AI，纯本地规则
  - 阶段 4 串行（v0.3 风格），批间 sleep 限速
  - 阶段 5 兜底，不保证 L4 精确
  - 任何段都不抛异常（fail-safe：返回 fallback）
"""

import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional


# ── 路径（与现有 ETL 一致） ─────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB_PATH = DATA_DIR / "category_v2_rules.db"
L4_PATTERNS_PATH = DATA_DIR / "l4_patterns.json"


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


# ── L4 pattern 规则（基于 spec 文本推断 L3）── MVP 内置，后续迁 l4_patterns.json
# 键: 正则；值: (l3, confidence)
# 设计：spec 里的型号/规格字符串通常比 breed 更精确
L4_PATTERNS_BUILTIN: list = [
    # ── 03 给排水
    (re.compile(r"PP-?R", re.I),                                ("03.01.02", 0.85)),  # PP-R 塑料给水管
    (re.compile(r"UPVC|PVC-?U", re.I),                          ("03.02.02", 0.85)),  # UPVC 塑料排水管
    (re.compile(r"^DN\d+|焊接钢管|镀锌", re.I),                ("03.01.01", 0.80)),  # 金属给水管
    (re.compile(r"承插|铸铁", re.I),                            ("03.02.01", 0.80)),  # 金属排水管
    (re.compile(r"闸阀|截止阀|球阀|蝶阀", re.I),                ("03.03.01", 0.90)),  # 通用阀门

    # ── 04 电气
    (re.compile(r"YJV|YJLV|交联|电力电缆", re.I),                ("04.02.01", 0.85)),
    (re.compile(r"BV|BVR|RVV|RVS|铜芯|铝芯", re.I),             ("04.03.01", 0.85)),
    (re.compile(r"配电箱|PZ30|XL", re.I),                       ("04.01.01", 0.80)),
    (re.compile(r"配电柜|GGD|低压柜", re.I),                     ("04.01.02", 0.80)),
    (re.compile(r"LED|金卤|荧光|筒灯|射灯", re.I),               ("04.04.01", 0.80)),
    (re.compile(r"开关|插座|面板", re.I),                       ("04.04.02", 0.80)),

    # ── 05 暖通
    (re.compile(r"风机盘管|FPC|FCU", re.I),                     ("05.02.01", 0.85)),
    (re.compile(r"空调机组|AHU|多联机", re.I),                   ("05.02.02", 0.80)),
    (re.compile(r"散热器|暖气片|铸铁暖气", re.I),               ("05.03.01", 0.85)),
    (re.compile(r"地暖管|PE-?RT|PE-?X", re.I),                   ("05.03.02", 0.85)),
    (re.compile(r"镀锌铁皮|通风管道|风管", re.I),               ("05.01.01", 0.80)),

    # ── 06 智能化
    (re.compile(r"网线|UTP|FTP|六类|超五类", re.I),              ("06.01.01", 0.85)),
    (re.compile(r"摄像头|摄像机|球机|枪机", re.I),               ("06.02.01", 0.85)),
    (re.compile(r"门禁|对讲|读卡器", re.I),                     ("06.02.02", 0.85)),
    (re.compile(r"烟感|温感|探测器|感烟", re.I),                 ("06.03.01", 0.85)),
    (re.compile(r"报警|联动|警铃", re.I),                       ("06.03.02", 0.80)),

    # ── 01 建筑
    (re.compile(r"螺纹钢|线材|盘螺|HRB|HPB", re.I),              ("01.04.01", 0.85)),  # 钢构件
    (re.compile(r"商品砼|混凝土|C\d+", re.I),                   ("01.03.01", 0.80)),  # 现浇混凝土基础（粗分类）
    (re.compile(r"页岩砖|多孔砖|实心砖|加气块|砌块", re.I),     ("01.02.02", 0.85)),
    (re.compile(r"水泥|P\.\d+ O\.\d+|P\.\d+", re.I),            ("01.05.01", 0.80)),  # 金属构件近似（实际是水泥胶凝，但 MVP 兜底）

    # ── 07 市政
    (re.compile(r"沥青|混凝土路面|路面砖", re.I),               ("07.01.01", 0.85)),
    (re.compile(r"桥板|桥墩|涵管", re.I),                       ("07.02.01", 0.85)),
    (re.compile(r"球墨铸铁|PE给水|市政给水", re.I),             ("07.03.01", 0.85)),
    (re.compile(r"HDPE|双壁波纹|市政排水", re.I),               ("07.03.02", 0.85)),

    # ── 08 园林
    (re.compile(r"苗木|乔木|灌木|香樟|银杏", re.I),             ("08.01.01", 0.85)),
    (re.compile(r"草坪|草皮|地被", re.I),                       ("08.01.02", 0.85)),
    (re.compile(r"园路|铺装|景石|置石", re.I),                   ("08.02.01", 0.80)),
    (re.compile(r"雕塑|小品|坐凳|指示牌", re.I),               ("08.03.01", 0.80)),

    # ── 02 装饰
    (re.compile(r"石膏板|矿棉板|硅钙板|铝扣板", re.I),           ("02.03.01", 0.85)),  # 吊顶
    (re.compile(r"断桥铝|铝合金窗|塑钢窗", re.I),               ("02.04.01", 0.85)),  # 金属门窗
    (re.compile(r"UPVC窗|PVC窗", re.I),                         ("02.04.02", 0.80)),  # 塑料门窗
    (re.compile(r"钢化玻璃|夹胶玻璃|中空玻璃|幕墙玻璃", re.I),   ("02.05.01", 0.85)),
    (re.compile(r"花岗岩|大理石|石材板", re.I),                 ("02.05.02", 0.85)),
    (re.compile(r"乳胶漆|氟碳漆|真石漆|防火涂料", re.I),         ("02.02.02", 0.85)),
    (re.compile(r"砂浆|抹面|抗裂砂浆", re.I),                   ("02.02.01", 0.80)),
    (re.compile(r"瓷砖|地砖|墙砖|面砖", re.I),                   ("02.01.02", 0.85)),
    (re.compile(r"自流平|环氧|耐磨地坪", re.I),                 ("02.01.01", 0.80)),
]


# ── Unit 兜底（阶段 5）── 粗粒度分类
UNIT_FALLBACK_MAP: dict = {
    "m":  ("03.01.01", 0.30),       # 长度类 → 金属给水管（最常见的 m 计量管材）
    "m²": ("02.01.01", 0.30),       # 面积类 → 整体面层
    "m³": ("01.03.01", 0.30),       # 体积类 → 现浇混凝土基础
    "kg": ("01.05.01", 0.30),       # 重量类 → 金属构件
    "t":  ("01.04.01", 0.30),       # 吨 → 钢构件
    "个": ("04.04.02", 0.30),       # 个 → 开关插座
    "套": ("03.04.01", 0.30),       # 套 → 卫生洁具
    "片": ("05.03.01", 0.30),       # 片 → 散热器
    "株": ("08.01.01", 0.30),       # 株 → 苗木
    "台": ("04.01.01", 0.30),       # 台 → 成套配电箱
    "块": ("01.02.01", 0.30),       # 块 → 砖砌体
    "樘": ("02.04.01", 0.30),       # 樘 → 金属门窗
}


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
    """根据 L3 码查 category_v2 表完整节点"""
    row = conn.execute(
        """SELECT l1, l2, l3, l4, gb_50500, quota_ref, ifc_class, uniclass_ss,
                  eng_part, eng_stage, main_or_aux, unit, billing_unit,
                  cost_method, name_l1, name_l2, name_l3
           FROM category_v2 WHERE l3 = ? LIMIT 1""",
        (l3,),
    ).fetchone()
    if not row:
        return None
    return {
        "l1": row[0], "l2": row[1], "l3": row[2], "l4": row[3],
        "gb_50500": row[4], "quota_ref": row[5], "ifc_class": row[6],
        "uniclass_ss": row[7], "eng_part": row[8], "eng_stage": row[9],
        "main_or_aux": row[10], "unit": row[11], "billing_unit": row[12],
        "cost_method": row[13], "name_l1": row[14], "name_l2": row[15],
        "name_l3": row[16],
    }


def _format_result(node: dict, source: str, confidence: float) -> dict:
    """把 DB 节点 + 来源 + 置信度打包成 v2 分类结果"""
    return {
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


# ── 5 段式 ─────────────────────────────────────────────────────────────

def _stage1_db_exact(conn: sqlite3.Connection, breed_clean: str) -> Optional[dict]:
    """阶段 1: breed_l3_map 表精确匹配"""
    if not breed_clean:
        return None
    row = conn.execute(
        "SELECT l3, source, confidence FROM breed_l3_map WHERE breed_clean = ? LIMIT 1",
        (breed_clean,),
    ).fetchone()
    if not row:
        return None
    l3, source, conf = row
    node = _load_category_node(conn, l3)
    if not node:
        return None
    return _format_result(node, "db_exact_v2", float(conf or 1.0))


def _stage2_db_fuzzy(conn: sqlite3.Connection, breed_clean: str) -> Optional[dict]:
    """阶段 2: Jaccard 模糊召回（TOP 1，confidence >= 0.6）
    MVP 阶段：先实现简化版——在 breed_l3_map 里查 Jaccard 相似度最高且 >= 0.6 的项。
    完整 Jaccard 算法在 gov_price_etl.classify.rules.jaccard（v1 已有，此处复用思路）。
    """
    if not breed_clean:
        return None
    target = set(breed_clean)
    rows = conn.execute(
        "SELECT breed_clean, l3, source, confidence FROM breed_l3_map"
    ).fetchall()
    if not rows:
        return None

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

    if not best or best_score < 0.6:
        return None
    l3, source, conf = best
    node = _load_category_node(conn, l3)
    if not node:
        return None
    return _format_result(node, "db_fuzzy_v2", round(best_score, 3))


def _stage3_pattern(conn: sqlite3.Connection, breed: str, spec: str) -> Optional[dict]:
    """阶段 3: L4 pattern 规则（breed + spec 联合正则 → L3 推断）
    注：实际生产中 pattern 应该针对 spec（spec 才有规格型号），但 MVP 阶段
    兼顾 breed 文本（如 "PP-R 冷水管" 中 PP-R 是关键标识），合并搜索更准确。
    """
    haystack = f"{breed} {spec}".strip()
    if not haystack:
        return None
    for pattern, (l3, conf) in L4_PATTERNS_BUILTIN:
        if pattern.search(haystack):
            node = _load_category_node(conn, l3)
            if node:
                return _format_result(node, "pattern_v2", conf)
    return None


def _stage4_ai(breed: str, spec: str, unit: str, breed_clean: str) -> Optional[dict]:
    """阶段 4: AI 分类（结构化输出 L1-L3 + 9 字段）—— 串行批次
    MVP 阶段：此函数先 return None（不调 AI），让阶段 5 兜底。
    后续接入：ai.service.classify_v2_batch
    """
    return None


def _stage5_unit_fallback(conn: sqlite3.Connection, unit: str) -> Optional[dict]:
    """阶段 5: unit 兜底（基于 unit 推断 L3）"""
    if not unit:
        return None
    u = unit.strip()
    if u not in UNIT_FALLBACK_MAP:
        # 兜底再兜底：标准化（m3 → m³）
        norm = {"m3": "m³", "m2": "m²"}.get(u, u)
        if norm not in UNIT_FALLBACK_MAP:
            return None
        u = norm
    l3, conf = UNIT_FALLBACK_MAP[u]
    node = _load_category_node(conn, l3)
    if not node:
        return None
    return _format_result(node, "fallback_v2", conf)


# ── 主入口 ─────────────────────────────────────────────────────────────

def classify_v2(
    breed: str,
    spec: str,
    unit: str,
    breed_clean: str,
    db_path: Optional[str] = None,
) -> dict:
    """
    4 层分类主入口（5 段式）。
    返回结构化结果，category_v2_source 标识命中段。
    任何异常都不抛，返回 fallback。
    """
    try:
        path = db_path or str(DEFAULT_DB_PATH)
        # 拿一个保证活着的连接（自动重连，健壮）
        conn = _ensure_alive_conn(path)
        # 注意：不用 try/finally conn.close()——这是单例，进程退出才关
        for stage_fn in (
            lambda: _stage1_db_exact(conn, breed_clean),
            lambda: _stage2_db_fuzzy(conn, breed_clean),
            lambda: _stage3_pattern(conn, breed, spec),
            lambda: _stage4_ai(breed, spec, unit, breed_clean),
            lambda: _stage5_unit_fallback(conn, unit),
        ):
            hit = stage_fn()
            if hit is not None:
                return hit
        # 理论上不会到这里（fallback 总能命中），但兜底
        return _format_result(
            {"l1": "", "l2": "", "l3": "", "l4": "UNCLASSIFIED",
             "name_l1": "", "name_l2": "", "name_l3": ""},
            "no_match_v2", 0.0,
        )
    except Exception as e:
        # fail-safe：库文件不存在等异常 → 返回空结果
        return {
            "l1": "", "l2": "", "l3": "", "l4": "UNCLASSIFIED",
            "category_v2_source": "error_v2",
            "category_v2_confidence": 0.0,
            "error": str(e),
        }


# ── 批量入口（ETL 用）─────────────────────────────────────────────────

def classify_v2_batch(
    items: list,
    db_path: Optional[str] = None,
    use_ai: bool = False,
) -> list:
    """
    批量分类入口（ETL 阶段 3 调 AI 时用）
    items: [{"breed": ..., "spec": ..., "unit": ..., "breed_clean": ...}, ...]
    返回: 同长度 list，每项是 classify_v2 的结果
    use_ai: True 时启用阶段 4（生产环境），False 时跳过（测试环境）
    """
    results = []
    t0 = time.time()
    for i, item in enumerate(items):
        result = classify_v2(
            breed=item.get("breed", ""),
            spec=item.get("spec", ""),
            unit=item.get("unit", ""),
            breed_clean=item.get("breed_clean", ""),
            db_path=db_path,
        )
        results.append(result)
    elapsed = time.time() - t0
    print(f"[classify_v2] {len(items)} 条 / {elapsed:.2f}s / {len(items)/elapsed if elapsed else 0:.1f} 条/s")
    return results


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

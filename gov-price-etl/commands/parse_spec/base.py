#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parse_spec/base.py - 通用规格解析基类

架构说明：
  - 规则唯一来源：vector_store（SQLite + blob）
  - parse() 按 ATTR_SLOTS 槽位制解析，每个 slot 独立竞争
  - RAG 召回（vector_store.search）替代线性遍历
  - fix-case API confirm 时写入向量库（同步写入 rules/*.py 作为备份）
  - rules/*.py 不再作为解析时的数据源，仅作备份/人工审查用

槽位制解析（修复 A/B/C 短路）：
  - 每个 attr 槽位独立竞争，不 first-match-return
  - 混合相似度：embedding cosine + keyword Jaccard
"""
import re
import json
import os
import glob
import urllib.request
import urllib.error
import threading

# ─── 向量库（唯一来源）─────────────────────────────────────────
try:
    from .rules.vector_store import get_vec_store
except Exception:
    get_vec_store = None

# ─── 属性解析槽位（动态从 _attrs.py 加载）────────────────────
try:
    import re as _re
    _content = open(os.path.join(os.path.dirname(__file__), "rules", "_attrs.py")).read()
    _arrow = chr(0x2192)
    _lines = [l for l in _content.split('\n') if _arrow in l and not l.strip().startswith('#')]
    _keys = [k for line in _lines for k in _re.findall(r'"(\w+)"', line.split(_arrow)[0])]
    ATTR_SLOTS = _keys if _keys else [
        "diameter", "thickness", "length", "width", "height",
        "material", "grade", "pressure", "cores", "voltage","current",
        "form","color","series","temperature"
    ]
except Exception:
    ATTR_SLOTS = [
        "diameter", "thickness", "length", "width", "height",
        "material", "grade", "pressure", "cores", "voltage","current",
        "form","color","series","temperature"
    ]

# ─── RAG 召回（向量库检索，替代线性遍历）─────────────────────

def _rag_candidates(spec: str, category: str, breed: str, attr_filter: str) -> list:
    """通过向量库召回候选规则，返回 [(pattern, attr, note, code), ...]
    attr_filter 为空字符串时执行全量召回（不过滤）

    规则库的 category 字段为空字符串（''）是常态（1719 条规则均如此），
    因此 category 精确匹配几乎必然返回 0，需要按 breed 回退。"""
    if get_vec_store is None:
        return []
    try:
        vs = get_vec_store()
        # 1. 按 category + breed 查
        results = vs.search(spec="", category=category, breed=breed,
                            top_k=20, attr_filter=attr_filter if attr_filter else None)
        # 2. breed 精确匹配为 0 时，忽略 breed，按 category 回退（breed='' 会命中泛化规则）
        if not results and breed:
            results = vs.search(spec="", category=category, breed="",
                                top_k=20, attr_filter=attr_filter if attr_filter else None)
        # 3. category + breed 全 0 时，仅按 category 查（category 为空则查全量）
        if not results and category:
            results = vs.search(spec="", category=category, breed="",
                                top_k=20, attr_filter=attr_filter if attr_filter else None)
        return [(r["pattern"], r["attr"], r["note"], r["code"]) for _, r in results]
    except Exception:
        return []


# ─── AI 配置 ──────────────────────────────────────────────────
FIX_CASE_API = "http://localhost:5200/api/stats/spec-quality/fix-case"
FIX_CASE_TOKEN = ""
try:
    with open("/Users/pengfit/.openclaw/openclaw.json") as f:
        FIX_CASE_TOKEN = json.load(f).get("gateway", {}).get("auth", {}).get("token", "")
except Exception:
    pass


def clean_spec(spec: str) -> str:
    """清洗原始 spec 字符串"""
    if not spec or spec in ("/", ""):
        return ""
    s = str(spec).strip()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _call_fix_case(spec: str, breed: str = "", category: str = "", confirm: bool = True) -> dict:
    """调用 fix-case API 生成并写入规则（confirm=True 写入向量库）"""
    body = json.dumps({
        "city": "xian",
        "spec": spec,
        "breed": breed,
        "category": category,
        "expected": {},
        "confirm": confirm,
    }).encode("utf-8")
    req = urllib.request.Request(
        FIX_CASE_API,
        data=body,
        headers={
            "Authorization": f"Bearer {FIX_CASE_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return {"ok": False}


class BaseParseSpec:
    """
    规格解析基类

    解析流程：
      - 每个 attr 槽位独立竞争，RAG 召回候选规则
      - 不再 first-match-return，填完所有 slot（或全部未命中）才返回
      - 全部未命中 → 调用 fix-case API

    规则来源：vector_store（SQLite + blob），唯一数据源。
    """

    def parse(self, spec: str, breed: str = "", category: str = "") -> dict:
        """
        全量 RAG 召回，每个 attr_name 独立竞争，命中即写入。
        支持动态字段：不在 ATTR_SLOTS 中的 attr_name 自动被捕获。
        """
        if not spec or spec == "/":
            return {}

        resolved = {}
        claimed = set()

        all_candidates = _rag_candidates(spec, category, breed, attr_filter="")
        for pattern, attr_name, note, code in all_candidates:
            if attr_name in claimed:
                continue

            try:
                m = re.search(pattern, spec)
                if not m:
                    continue
            except re.error:
                continue

            exec_result = {}
            if code:
                safe_globals = {"re": re, "result": exec_result, "s": spec}
                try:
                    exec(code, safe_globals)
                except Exception:
                    pass

            if exec_result:
                val = exec_result.get(attr_name) or list(exec_result.values())[0]
            else:
                groups = m.groups()
                if len(groups) >= 1:
                    val = groups[0]
                else:
                    val = m.group(0)

            if val:
                resolved[attr_name] = val
                claimed.add(attr_name)

        return resolved
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

命名规范：
  - parse() 返回的 attr 名称统一为"干净"名称（无 attr_ 前缀）
  - 规则库中 attr='attr_diameter' 等效于 attr='diameter'，统一规范输出
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

# ─── 属性解析槽位（动态从 _attrs.py 加载 + 扩展 attr_ 前缀别名）────
#
# _attrs.py 定义 32 个基础槽位（无 attr_ 前缀）。
# 规则库中 754 条规则使用 attr_ 前缀命名（如 attr_diameter, attr_nominal_diameter）。
# 为确保这些规则能被召回，ATTR_SLOTS 需同时包含原始名和 attr_ 前缀别名。
_ATTR_PREFIX_EXTRAS = [
    # 来自规则库的高频 attr_* 属性（按覆盖文档数排序）
    "attr_type", "attr_thickness", "attr_diameter", "attr_outer_diameter",
    "attr_wall_thickness", "attr_width", "attr_nominal_diameter", "attr_height",
    "attr_size", "attr_strength_grade", "attr_material_grade", "attr_cross_section",
    "attr_gram_weight", "attr_granule_size", "attr_packaging", "attr_power",
    "attr_diameter_range", "attr_dimensions", "attr_thickness_range",
    "attr_seedling_size", "attr_max_particle_size", "attr_flange_thickness",
    "attr_cores", "attr_series", "attr_model", "attr_dbh", "attr_thread",
    "attr_thermal_conductivity", "attr_origin", "attr_lights", "attr_current",
    "attr_container_type", "attr_coating_weight", "attr_surface", "attr_strength",
    "attr_granule_size", "attr_compression_strength", "attr_water_absorption",
    "attr_spec", "attr_size_range", "attr_ratio", "attr_rated_load",
    "attr_pressure", "attr_length_range", "attr_crown_width", "attr_cement_content",
]

try:
    import re as _re
    _content = open(os.path.join(os.path.dirname(__file__), "rules", "_attrs.py")).read()
    _arrow = chr(0x2192)
    _lines = [l for l in _content.split('\n') if _arrow in l and not l.strip().startswith('#')]
    _keys = [k for line in _lines for k in _re.findall(r'"(\w+)"', line.split(_arrow)[0])]
    _BASE_SLOTS = _keys if _keys else [
        "diameter", "thickness", "length", "width", "height",
        "material", "grade", "pressure", "cores", "voltage", "current",
        "form", "color", "series", "temperature"
    ]
    ATTR_SLOTS = _BASE_SLOTS + [k for k in _ATTR_PREFIX_EXTRAS if k not in _BASE_SLOTS]
except Exception:
    ATTR_SLOTS = [
        "diameter", "thickness", "length", "width", "height",
        "material", "grade", "pressure", "cores", "voltage", "current",
        "form", "color", "series", "temperature",
    ] + [k for k in _ATTR_PREFIX_EXTRAS]

# ─── RAG 召回（向量库检索，替代线性遍历）─────────────────────

# 2026-07-05 性能优化：预编译 pattern，避免每次 re.search 重复编译。
# 实测 cProfile：500 docs 调用 parse() → 901K 次 re._compile 占 66% 时间。
# 改为：模块级 LRU 缓存 pattern → compiled_regex。
# 规则库 ~3000 条 pattern，一次性编译缓存；后续 re.search 走 fast path。
import functools as _ft
_PATTERN_COMPILE_CACHE: dict = {}  # pattern_str -> compiled_regex or None (compile error)


def _get_compiled_pattern(pat: str):
    """懒加载 + 模块级缓存：pattern → compiled regex。None 表示编译失败。"""
    if pat not in _PATTERN_COMPILE_CACHE:
        try:
            _PATTERN_COMPILE_CACHE[pat] = re.compile(pat)
        except re.error:
            _PATTERN_COMPILE_CACHE[pat] = None
    return _PATTERN_COMPILE_CACHE[pat]


def _rag_candidates(spec: str, category: str, breed: str, attr_filter: str) -> list:
    """通过向量库召回候选规则，返回 [(compiled_pattern, attr, note, code), ...]

    2026-07-05 性能优化：返回预编译 regex 对象（避免 parse() 循环内重复编译）。

    关键设计：
    - 规则库 1064/1098 条有具体 category（如'砌体墙体材料'、'钢材金属材料'），
      用精确 category 过滤会阻断 97% 的规则。
    - breed 精确过滤同样会导致漏召回（如'砖渣多孔砖'无精确规则）。
    - 改为：跳过 category+breed 过滤，完全依赖 Jaccard 相似度召回。
      Jaccard score >= 0.001 的规则即为候选，再经 regex 最终匹配。
    - 必须传 spec=spec 而非 spec=''，否则 Jaccard 评分失效。
    """
    if get_vec_store is None:
        return []
    try:
        vs = get_vec_store()
        # 跳过 category 和 breed 过滤，纯靠 Jaccard 召回 + regex 最终验证
        # 注意：2026-07-04 fix — search() 内部对 breed/category 用精确匹配 SQL 过滤，
        # breed='球墨铸铁给水管DN100' 会把所有 breed='球墨铸铁给水管' 的规则排除掉。
        # 这里传空字符串让 SQL 跳过对应过滤，规则全量召回后由 Jaccard + regex 双层把关。
        # 2026-07-04 fix2 — 调大 top_k=5000，因为通用空 breed 规则 score 较低（0.37），
        # 容易被有 breed 的具体规则（0.575）挤出 top 500，导致电缆/管材 N*M 通用规则不命中。
        results = vs.search(
            spec=spec,
            category=category,
            breed="",  # 传空跳过 breed 精确过滤
            top_k=5000,
            attr_filter=attr_filter if attr_filter else None,
        )
        # 预编译 pattern，过滤编译失败的规则
        out = []
        for _, r in results:
            cp = _get_compiled_pattern(r["pattern"])
            if cp is not None:
                out.append((cp, r["attr"], r.get("note", ""), r.get("code", "")))
        return out
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
        for compiled_pattern, attr_name, note, code in all_candidates:
            if attr_name in claimed:
                continue

            # 2026-07-05 优化：compiled_pattern 已预编译，直接 search
            m = compiled_pattern.search(spec)
            if not m:
                continue

            exec_result = {}
            if code:
                # 规则库 code 首行无缩进、后续行有缩进，dedent 无效；改用：找首行之后的首个缩进作基准，统一去缩进
                lines = code.split("\n")
                base_indent = None
                for l in lines[1:]:
                    stripped = l.lstrip(" ")
                    if stripped:
                        base_indent = len(l) - len(stripped)
                        break
                if base_indent is None:
                    base_indent = 0
                clean_lines = []
                for l in lines:
                    stripped = l.lstrip(" ")
                    if stripped:
                        ws = len(l) - len(stripped)
                        clean_lines.append(l[base_indent:] if ws >= base_indent else l[ws:])
                    else:
                        clean_lines.append("")
                clean_code = "\n".join(clean_lines)
                safe_globals = {"re": re, "result": exec_result, "s": spec}
                try:
                    exec(clean_code, safe_globals)
                except Exception:
                    pass

            if exec_result:
                # Multi-output rule: merge all attr results from code
                for k, v in exec_result.items():
                    # 规范命名：去掉 attr_ 前缀，统一为"干净"名称
                    norm_k = k[5:] if k.startswith("attr_") else k
                    if v and norm_k not in claimed:
                        resolved[norm_k] = v
                        claimed.add(norm_k)
            elif not code:
                # 无 code 时用 regex groups 做 fallback（纯正则规则）
                groups = m.groups()
                val = groups[0] if len(groups) >= 1 else m.group(0)
                norm_attr = attr_name[5:] if attr_name.startswith("attr_") else attr_name
                if val and norm_attr not in claimed:
                    resolved[norm_attr] = val
                    claimed.add(norm_attr)
            # else: code 存在但 exec 失败 → 跳过，不 claim attr，留给其他规则

        return resolved
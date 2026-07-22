#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parse_spec/base.py - 通用规格解析基类

架构说明：
  - 规则唯一来源：vector_store（SQLite + blob）
  - parse() 按 ATTR_SLOTS 槽位制解析，每个 slot 独立竞争
  - RAG 召回（vector_store.search）替代线性遍历
  - 规则确认 / 案例生产路径已下线（2026-07-18）；新规则通过 sync_dws stage 3 AI 解析回写
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

# ─── catch-all 拦截（2026-07-18）──────────────────────────
# 场景：纯文字 spec（如"珍珠岩"、"综合"）被 catch-all 规则填到 material/type/grade，
# 导致 attr 写"material='240*115*53'"这种把原 spec 当 material 的污染值。
# 拦截策略：catch-all 类 attr 键 + value 与 spec 相同 → 不写入（兜底规则不算解析成功）。
_CATCH_ALL_KEYS = frozenset({"material", "type", "grade", "spec", "note", "feature", "usage"})

# catch-all 禁填清单 (2026-07-22 v0.10): 任何 catch-all 路径都不许写这些 key。
# 例子: spec='板厚0.5mm' 的 0.5 被强制套 'm³' 填入 volume;
#       spec='0.5~1.5cm' 的 0.5 被填入 thickness_min/package_type。
# 从 monorepo data/attr_filters.json 加载 (forbidden_keys), 失败则用 fallback 默认集。
try:
    import json as _json_forbidden
    from gov_price_etl.paths import DATA_DIR as _DATA_DIR_FBN, ETL_PROJECT_ROOT as _ETL_ROOT_FBN
    _forbidden_keys_fallback = frozenset({"volume", "package_type", "height_min", "thickness_min", "cross_section_area"})
    _forbidden_loaded = None
    for _p in (_DATA_DIR_FBN / "attr_filters.json", _ETL_ROOT_FBN / "data" / "attr_filters.json"):
        if _p.exists():
            try:
                with open(_p, encoding="utf-8") as _f:
                    _forbidden_loaded = frozenset(_json_forbidden.load(_f).get("forbidden_keys", []))
                    break
            except Exception:
                continue
    _CATCH_ALL_FORBIDDEN_KEYS = _forbidden_loaded or _forbidden_keys_fallback
except Exception:
    _CATCH_ALL_FORBIDDEN_KEYS = frozenset({"volume", "package_type", "height_min", "thickness_min", "cross_section_area"})

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


_RAG_MIN_RESULTS = 10  # 召回不足阈值,低于此数量则用 breed="" 兜底二次召回


def _type_field_breed_guard(norm_k: str, v, breed: str) -> bool:
    """type 字段 L1 语义护栏(2026-07-22 v0.13 治本补丁)。

    触发条件:norm_k == 'type' 且 v 含中文字符 且 breed 非空且含中文字符。
    判定:bigram(breed) ∩ bigram(v) 为空 → 跨类目串料,丢弃。

    例:
      breed='碎石' + v='消防智能应急照明' → 交集空 → 丢 ✓
      breed='碎石' + v='5-10mm'            → v 不含中文 → 放行 ✓
      breed='消防智能应急照明' + v='消防智能应急照明' → 交集非空 → 放行 ✓
    """
    if norm_k != "type":
        return True
    if not breed:
        return True
    s = str(v).strip()
    if not s:
        return True
    # 数字/字母/符号型 type 值 → 放行(避免误伤 '5-10mm' / 'SG24B' 等)
    if not any("\u4e00" <= c <= "\u9fff" for c in s):
        return True
    breed_cn = "".join(c for c in breed if "\u4e00" <= c <= "\u9fff")
    val_cn = "".join(c for c in s if "\u4e00" <= c <= "\u9fff")
    if not breed_cn:
        return True  # breed 自身全非中文,无法语义判定 → 放行
    breed_grams = {breed_cn[i:i + 2] for i in range(len(breed_cn) - 1)}
    val_grams = {val_cn[i:i + 2] for i in range(len(val_cn) - 1)}
    return bool(breed_grams & val_grams)


def _rag_candidates(spec: str, category: str, breed: str, l3: str = "", attr_filter: str = "") -> list:
    """通过向量库召回候选规则，返回 [(compiled_pattern, attr, note, code), ...]

    2026-07-05 性能优化：返回预编译 regex 对象（避免 parse() 循环内重复编译）。
    v0.8+: category 参数已弃用,内部不再传给 search()。L3 + breed 主导召回。

    关键设计：
    - 规则库 1064/1098 条有具体 category（如'砌体墙体材料'、'钢材金属材料'），
      用精确 category 过滤会阻断 97% 的规则。
    - breed 精确过滤同样会导致漏召回(如'砖渣多孔砖'无精确规则)。

    2026-07-22 v0.13 治本补丁:
    - 召回仍传 breed=""(与原行为兼容,不破坏既有测试)
    - 新增 post-filter:规则 breed 与当前 breed 字符重叠度<阈值(如 1 个字)直接 drop
    - 例:rule.breed='消防智能应急照明' + current.breed='碎石' → 重叠 0 → 丢弃
      (这条规则就是 id=754,导致 4047 条 type=消防智能应急照明 污染)

    - 必须传 spec=spec 而非 spec='',否则 Jaccard 评分失效。
    """
    if get_vec_store is None:
        return []
    try:
        vs = get_vec_store()
        # v0.13: 保持原行为 breed="",不破坏既有召回/测试
        # 注:carefully 从 v0.8 沿用,2026-07-04 fix 详注释保留
        results = vs.search(
            spec=spec,
            breed="",  # 传空跳过 breed 精确过滤(原行为)
            l3=l3,
            top_k=5000,
            attr_filter=attr_filter if attr_filter else None,
        )

        # v0.13 治本补丁:post-filter 拦截跨品种的强写型规则(754/755 类)
        # 只在 rule.breed 与 current breed 字符重叠低于阈值时拦截
        if breed:
            cur_chars = set(c for c in breed if '\u4e00' <= c <= '\u9fff')
            results = [
                (score, r) for score, r in results
                if _rule_breed_filter(r.get("breed", ""), cur_chars)
            ]

        # 2026-07-18: 过滤软删除的规则（attr 以 __deleted__ 开头）
        results = [(score, r) for score, r in results if not r["attr"].startswith("__deleted__")]
        # 预编译 pattern,过滤编译失败的规则
        out = []
        for _, r in results:
            cp = _get_compiled_pattern(r["pattern"])
            if cp is not None:
                out.append((cp, r["attr"], r.get("note", ""), r.get("code", "")))
        return out
    except Exception:
        return []


def _rule_breed_filter(rule_breed: str, current_breed_chars: set) -> bool:
    """跨品种 bug 规则拦截 (2026-07-22 v0.13)。

    Args:
      rule_breed: 规则库中规则的 breed 字段
      current_breed_chars: 当前 doc 的 breed 中文 char 集合

    Returns:
      True = 保留(False = 拦截)

    规则:
      1) rule_breed 为空 → 保留 (通用规则,放行)
      2) rule_breed 非空但 current breed 为空 → 保留 (无依据判断)
      3) 两边都有中文 → 计算交集,交集空 → 拦截 (跨类目)
      4) 单边 (rule_breed 短, 如'碎石') 优先按字符交集判定
    """
    if not rule_breed:
        return True
    if not current_breed_chars:
        return True
    rule_chars = set(c for c in rule_breed if '\u4e00' <= c <= '\u9fff')
    if not rule_chars:
        return True  # rule_breed 全非中文,无法判断 → 放行
    # 至少 1 个中文字符交集
    return bool(rule_chars & current_breed_chars)


# ─── AI 配置 ──────────────────────────────────────────────────
class BaseParseSpec:
    """
    规格解析基类

    解析流程：
      - 每个 attr 槽位独立竞争，RAG 召回候选规则
      - 不再 first-match-return，填完所有 slot（或全部未命中）才返回
      - 全部未命中 → 返空（不降级、不调外部 API）

    规则来源：vector_store（SQLite + blob），唯一数据源。
    """

    def parse(self, spec: str, breed: str = "", category: str = "", l3: str = "") -> dict:
        """
        全量 RAG 召回，每个 attr_name 独立竞争，命中即写入。
        支持动态字段：不在 ATTR_SLOTS 中的 attr_name 自动被捕获。
        """
        if not spec or spec == "/":
            return {}

        resolved = {}
        claimed = set()

        all_candidates = _rag_candidates(spec, category, breed, l3=l3, attr_filter="")
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
                    # 2026-07-22 catch-all 禁填：这些 key 任何 catch-all 路径都不许写
                    if norm_k in _CATCH_ALL_FORBIDDEN_KEYS:
                        continue
                    # 2026-07-18 catch-all 拦截：catch-all 类 attr 键 + value == spec → 跳过
                    # 防止 material='240*115*53' 这种 spec 原值回流污染
                    if norm_k in _CATCH_ALL_KEYS and str(v).strip() == spec.strip():
                        continue
                    # 2026-07-22 v0.13 治本:type 字段 L1 语义护栏
                    # 防 catch-all 规则库把跨品种写死型 type 值塞到当前 doc
                    if not _type_field_breed_guard(norm_k, v, breed):
                        continue
                    if v and norm_k not in claimed:
                        resolved[norm_k] = v
                        claimed.add(norm_k)
            elif not code:
                # 无 code 时用 regex groups 做 fallback（纯正则规则）
                groups = m.groups()
                val = groups[0] if len(groups) >= 1 else m.group(0)
                norm_attr = attr_name[5:] if attr_name.startswith("attr_") else attr_name
                # 2026-07-22 catch-all 禁填（纯正则路径）
                if norm_attr in _CATCH_ALL_FORBIDDEN_KEYS:
                    continue
                # 2026-07-18 catch-all 拦截（纯正则路径）
                if norm_attr in _CATCH_ALL_KEYS and str(val).strip() == spec.strip():
                    continue
                # 2026-07-22 v0.13 治本:type 字段 L1 语义护栏(纯正则路径同步)
                if not _type_field_breed_guard(norm_attr, val, breed):
                    continue
                if val and norm_attr not in claimed:
                    resolved[norm_attr] = val
                    claimed.add(norm_attr)
            # else: code 存在但 exec 失败 → 跳过，不 claim attr，留给其他规则

        return resolved
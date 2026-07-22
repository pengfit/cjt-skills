"""L1 字段标准化层

v0.2（2026-07-22）：
- 实现 sanitize_attr()：删脏/修错位/补字段
- 实现 normalize_cable_type()：GB/T 12706 电缆命名反解
- Phase B 待补：normalize_breed() 完整实现（依赖 breed_canonical.db）
"""
from __future__ import annotations
import re
from typing import Optional

from ..utils.data_loader import load_json
from ..utils.errors import UnknownAttrKeyError


# ── attr 净化规则（懒加载） ─────────────────────────────────────────────
_RULES = None
_CABLE_RULES = None


def _get_rules():
    global _RULES
    if _RULES is None:
        _RULES = load_json("attr_filters.json")
    return _RULES


def _get_cable_rules():
    global _CABLE_RULES
    if _CABLE_RULES is None:
        _CABLE_RULES = load_json("cable_type_rules.json")
    return _CABLE_RULES


def clear_cache():
    """测试用：清空 JSON 缓存。"""
    global _RULES, _CABLE_RULES, _L3_WHITELIST
    _RULES = None
    _CABLE_RULES = None
    _L3_WHITELIST = None


# ── v0.2 L3 类目白名单加载 ─────────────────────────────────────
_L3_WHITELIST = None


def _get_l3_whitelist() -> dict:
    """v3 L3 类目级 attr 白名单 (data/category_attr_whitelist.json)。"""
    global _L3_WHITELIST
    if _L3_WHITELIST is None:
        try:
            _L3_WHITELIST = load_json("category_attr_whitelist.json")
        except Exception:
            _L3_WHITELIST = {}
    return _L3_WHITELIST


def filter_by_l3_whitelist(parsed: dict, l3_code: Optional[str] = None) -> dict:
    """L3 类目白名单过滤。允许的 attr 放行；拒绝的拒；不在表内的走默认。

    Args:
        parsed: sanitize_attr 返回的 attr_norm 候选 dict
        l3_code: v3 三级分类码 (如 '04.05.07'). 传 None = 走 hard_reject 兜底（不过滤）

    Returns:
        过滤后的 attr dict (允许的留下, 拒绝的进 dropped)
    """
    if not l3_code or not parsed:
        return parsed
    whitelist = _get_l3_whitelist()
    by_l3 = whitelist.get("by_l3", {})
    rule = by_l3.get(l3_code)
    if not rule:
        return parsed  # 未配白名单的 L3, 不收紧 (避免过度拒新字段)
    allow_set = set(rule.get("allow") or [])
    deny_set = set(rule.get("deny") or [])
    if not allow_set and not deny_set:
        return parsed
    kept = {}
    dropped = []
    for k, v in parsed.items():
        if deny_set and k in deny_set:
            dropped.append((k, v, f"l3_deny:{l3_code}"))
            continue
        # allow_set 非空时, 仅允许的 k 保留 (其他先保守拒)
        if allow_set and k not in allow_set:
            dropped.append((k, v, f"l3_not_in_allow:{l3_code}"))
            continue
        kept[k] = v
    return {"attr_norm": kept, "dropped_by_l3": dropped}


def _hard_reject_match(hard_reject: list, k: str, v: str) -> Optional[str]:
    """检查 (k, v) 是否匹配 hard_reject 规则。匹配返回 reason 字符串, 不匹配返 None。

    支持的规则字段:
      - key              (必填): 仅匹配该 k
      - min_len          (可选): v 长度 >= 此值才算可疑（例: type='m' 1 字符太短）
      - value_contains   (可选): str 或 list, v 包含任一子串就算可疑（例: weight='17g/m²'）
      - value_regex      (可选): v 匹配该正则就算可疑（例: core_count='1234' 4 位以上）

    使用例:
        [{"key": "type", "min_len": 2}, {"key": "price"}, {"key": "weight", "value_contains": "g/m²"}]
    """
    for rule in hard_reject:
        if rule.get("key") != k:
            continue
        # value_contains
        vc = rule.get("value_contains")
        if vc:
            if isinstance(vc, str):
                vc = [vc]
            if any(sub in v for sub in vc):
                return rule.get("reason", f"value_contains:{vc}")
        # value_regex
        vr = rule.get("value_regex")
        if vr and re.search(vr, v):
            return rule.get("reason", f"value_regex:{vr}")
        # min_len (为占位表示: 仅 k 匹配 + value 长度 < min_len 拒)
        if "min_len" in rule and len(v) < rule["min_len"]:
            return rule.get("reason", f"min_len<{rule['min_len']}")
        # 仅 key 匹配（无条件, 一律拒）
        if not any(k in rule for k in ("value_contains", "value_regex", "min_len")):
            return rule.get("reason", f"key:{k}")
    return None


# ── 主入口：sanitize_attr ───────────────────────────────────────────────
def sanitize_attr(doc: dict, l3_code: Optional[str] = None) -> dict:
    """DWS attr[] → attr_norm[]，删脏/修错位/补字段 + 按品种 L3 类目白名单收紧。

    Args:
        doc: DWS 原始文档 (含 'attr' 字段)
        l3_code: v3 三级分类码 (如 '04.05.07' 电缆 / '03.05.01' 管材)。传 None = 仅走通用 hard_reject。

    返回：
        {
            "attr_norm": [{"k": ..., "v": ...}, ...],   # 干净 attr
            "dropped":   [(k, v, reason), ...],         # 被删条目（留痕）
            "promoted":  [{"k": new_k, "v": new_v}, ...],  # 改名/合项
            "empty":     bool,                          # 原始 attr 为空
        }

    净化规则（按 attr_filters.json + category_attr_whitelist.json 配置）：
        1. 空 attr (attr=[]) → 直接标 empty=True, attr_norm=[]
        2. 缺 k 或 v → 删
        3. forbidden_keys (volume / package_type) → 删
        4. forbidden_pairs (brand=DN/FN/PC/PE/PP/PVC) → 删
        5. material ∈ desc_words → 删（catch-all 把 spec 前缀当材质）
        6. promote (height_min→height_range, cross_section_area→cross_section 等)
        7. 数值字段 (numeric_required_digit) 无数字 → 删
        8. hard_reject (v0.2) 跨品种通用硬拒：type=单字母 / price / weight=g/m² / diameter=mm² 等
        9. L3 类目白名单 (v0.2) 按品种收紧：allow 内的放行 / deny 内的拒 / 不在表内的走默认
    """
    out: dict = {"attr_norm": [], "dropped": [], "promoted": [], "empty": False}
    attrs = doc.get("attr")

    # 规则 1: 空 attr (含 None / [] / 缺字段)
    if not attrs:
        out["empty"] = True
        return out

    rules = _get_rules()
    forbidden_keys = set(rules.get("forbidden_keys", []))
    forbidden_pairs = {(k, v) for k, v in rules.get("forbidden_pairs", [])}
    desc_words = set(rules.get("desc_words_for_material", []))
    promote_map = dict(rules.get("promote", {}))
    numeric_required = set(rules.get("numeric_required_digit", []))
    hard_reject = rules.get("hard_reject", [])  # v0.2 新增跨品种通用硬拒

    for kv in attrs:
        if not isinstance(kv, dict):
            out["dropped"].append((None, None, "not_dict"))
            continue

        k = kv.get("k")
        v = kv.get("v")

        # 规则 2: 缺 k 或 v
        if not k or v is None or str(v).strip() == "":
            out["dropped"].append((k, v, "empty_kv"))
            continue

        k, v = str(k).strip(), str(v).strip()

        # 规则 3: forbidden_keys
        if k in forbidden_keys:
            out["dropped"].append((k, v, f"forbidden_key:{k}"))
            continue

        # 规则 4: forbidden_pairs
        if (k, v) in forbidden_pairs:
            out["dropped"].append((k, v, f"forbidden_pair:{k}={v}"))
            continue

        # 规则 5: material 描述词污染
        if k == "material" and v in desc_words:
            out["dropped"].append((k, v, "material_desc"))
            continue

        # 规则 8 (v0.2): hard_reject 跨品种通用硬拒
        hr_reason = _hard_reject_match(hard_reject, k, v)
        if hr_reason:
            out["dropped"].append((k, v, f"hard_reject:{hr_reason}"))
            continue

        # 规则 6: promote (改名/合项)
        if k in promote_map:
            new_k = promote_map[k]
            new_v = _apply_promote_transform(k, v)
            out["promoted"].append({"k": new_k, "v": new_v, "from": {"k": k, "v": v}})
            out["attr_norm"].append({"k": new_k, "v": new_v})
            continue

        # 规则 7: 数值字段必须含数字
        if k in numeric_required and not re.search(r"\d", v):
            out["dropped"].append((k, v, "numeric_required_no_digit"))
            continue

        # 通过所有规则，保留
        out["attr_norm"].append({"k": k, "v": v})

    # 规则 9 (v0.2): L3 类目白名单收紧 (有 l3_code 时才生效)
    if l3_code and out["attr_norm"]:
        norm_dict = {item["k"]: item["v"] for item in out["attr_norm"]}
        wl_result = filter_by_l3_whitelist(norm_dict, l3_code)
        if isinstance(wl_result, dict) and "dropped_by_l3" in wl_result:
            for k, v, reason in wl_result["dropped_by_l3"]:
                out["dropped"].append((k, v, reason))
            out["attr_norm"] = [{"k": k, "v": v} for k, v in wl_result["attr_norm"].items()]

    return out


def _apply_promote_transform(orig_k: str, orig_v: str) -> str:
    """promote 时顺便做格式转换。

    height_min '80cm' + 已存在的 height → 合并为 height_range '80-90cm'
    简化版：只单独转换值，不合并（合并由 normalize_cable_type / 其他模块处理）
    """
    return orig_v


# ── 电缆型号归一（GB/T 12706 + GB/T 19666） ─────────────────────────────
def normalize_cable_type(doc: dict) -> dict:
    """识别电缆型号命名，从 spec 原文重拆字段。

    适用 breed 含 cable_breed_keywords 之一（如 电力电缆 / 控制电缆）。
    返回：
        applied=False 时: 不影响 doc
        applied=True 时:
            {
                "applied": True,
                "canonical_type": "YJV22",          # 重构后的型号
                "voltage":         "0.6/1kV",        # 规范化电压
                "core_count":      3,
                "cross_section":   "2.5mm²",
                "fire_rating":     "A级阻燃",        # 可选
                "armor_type":      "钢带铠装",       # 可选
                "drop_keys":       ["type"],          # 让 caller 删原错 type
            }
    """
    breed = (doc.get("breed") or "").strip()
    spec = (doc.get("spec") or "").strip()

    if not spec:
        return {"applied": False, "reason": "no_spec"}
    if not _is_cable_breed(breed):
        return {"applied": False, "reason": "not_cable_breed", "breed": breed}

    rules = _get_cable_rules()
    m = re.match(rules["spec_pattern"], spec, re.IGNORECASE)
    if not m:
        return {"applied": False, "reason": "no_pattern_match", "spec": spec}

    g = m.groupdict()
    # 信任正则捕获的 body（已经是 spec 中真实子串），
    # 不要做 substring 覆盖（之前的 _match_body_case 会让 KVV 退化成 VV）
    body = (g.get("body") or "").upper()
    armor = g.get("armor") or ""
    fire = (g.get("fire") or "").upper()
    voltage_raw = g.get("voltage") or ""
    core = int(g["core"]) if g.get("core") else None
    section = g.get("section") or ""

    # 铠装 + 主体 = canonical_type
    canonical_type = (body + armor) if armor else body

    # 阻燃/耐火
    fire_rating = rules["fire_codes"].get(fire) or rules["fire_codes"].get(fire.replace("-", "")) or None
    if not fire_rating and fire:
        fire_rating = fire  # 未知代码原样保留

    # 铠装类型
    armor_type = rules["armor_codes"].get(armor) or None

    # 电压规范化
    voltage = _canon_voltage(voltage_raw) if voltage_raw else None

    # 截面规范化
    cross_section = f"{section}mm²" if section else None

    return {
        "applied": True,
        "canonical_type": canonical_type,
        "voltage": voltage,
        "core_count": core,
        "cross_section": cross_section,
        "fire_rating": fire_rating,
        "armor_type": armor_type,
        "drop_keys": ["type"],
        "source_spec": spec,
    }


def _is_cable_breed(breed: str) -> bool:
    rules = _get_cable_rules()
    for kw in rules.get("cable_breed_keywords", []):
        if kw in breed:
            return True
    return False


def _canon_voltage(raw: str) -> str:
    """电压字符串规范化: '0.6/1KV' → '0.6/1kV'；'450/750V' → '450/750V'。"""
    s = raw.strip()
    # 大写 KV → 小写 kV
    s = re.sub(r"(\d)KV", r"\1kV", s)
    s = re.sub(r"(^|\s)KV", r"\1kV", s)
    return s


# ── Phase B 占位 ────────────────────────────────────────────────────────
def normalize_breed(raw: str, city: str) -> dict:
    """[Phase B] 品种名 → canonical + l3_code。

    Phase A 暂返回 raw 原值，便于上层先跑通流程。
    """
    raise NotImplementedError(
        "[L1 fields] normalize_breed 将在 Phase B 实现，依赖 breed_canonical.db。"
        "Phase A 直接用原始 breed 字段。"
    )


def normalize_attr_k(k: str) -> str:
    """[Phase B] attr.k → canonical_attr_key（如 DN → nominal_diameter）。"""
    return k  # v0.2 暂直接返回


def normalize_attr_v(k_canonical: str, v: str) -> str:
    """[Phase B] attr.v 归一（如 DN50 / DN 50 / Φ50 → DN-50）。"""
    return v  # v0.2 暂直接返回
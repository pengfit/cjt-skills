"""pipeline/dws_sync.py - DWD → DWS 三段式同步（明确节点）

新数据流（v0.3 重构）：
  ┌─────────────────────────────────────────────────────────────────────┐
  │ DWD source (attr 来自 ODS→DWD 阶段，可能为空)                        │
  │   │                                                                 │
  │   ├── 阶段 1：DWD attr 非空 → 直接同步 DWS                          │
  │   │     - 不调本地规则库、不调 AI                                     │
  │   │     - attr_source = 'etl'  （ODS→DWD 时已经解析过）              │
  │   │                                                                 │
  │   ├── 阶段 2：DWD attr 空 → 本地规则库 breed_spec_rules.db 解析     │
  │   │     - 调 BaseParseSpec.parse()（已重写为只查 vector_store）      │
  │   │     - 命中 → 回写 DWD attr + 同步 DWS                            │
  │   │     - attr_source = 'local_db'                                  │
  │   │                                                                 │
  │   └── 阶段 3：DWD attr 空 + 本地未命中 → AI batch_spec_parse 串行   │
  │         - 攒批（默认 20/批，串行调用，不并发）                        │
  │         - 命中 → 回写 DWD attr + 同步 DWS                            │
  │         - attr_source = 'ai' | 'ai_fallback'                        │
  └─────────────────────────────────────────────────────────────────────┘

每条 DWS 文档带 `attr_source` 字段，标识 attr 来源：
  'etl'         阶段 1 命中（DWD 已解析，ODS→DWD 阶段留下的）
  'local_db'    阶段 2 命中（本地 breed_spec_rules.db 解析）
  'ai'          阶段 3 AI 解析成功
  'ai_fallback' 阶段 3 AI 失败兜底（空 attr）

历史兼容：保留 sync_dws_plain / sync_dws_quick / sync_dws_with_ai 三个对外入口。
"""
import json
import re
import time
from collections import defaultdict
from typing import Callable, Optional, Tuple

import requests

from gov_price_etl.config import CITY_CONFIGS
from gov_price_etl.es_client import bulk_index, get_es_client
from gov_price_etl.indexer import ensure_indices
from gov_price_etl.parse_spec import get_parser
from gov_price_etl.transform import build_attr, flat_attr_to_nested, filter_by_l3_whitelist


# AI 解析串行批次大小（道友要求"串行"，默认 20/批，逐批调用 AI）
AI_PARSE_BATCH_SIZE = 20
AI_PARSE_BATCH_SLEEP_S = 0.5  # 批间限速


def _is_price_valid(d: dict) -> bool:
    """价格有效性检查：price_min 不为 None/0 才算有效。

    背景：甘孜州偏远区县 (sichuan) 、未发布价格的品种 等场景
    数据源未发布价格，被存为 0；这类文档写入 DWS 后会污染价格走势 / 排序 / 统计。

    v3 (2026-07-02) ：升级为看 price_min 区间的下界。
    区间价 '115-173' 会被 _parse_interval_price 解析为 price_min=115, price_max=173,
    即便中位数 price=144，也走这里返 True。绿化苗木的 '大于200' 被解析为
    price_min=price_max=200，同样能进 DWS。

    v4 (2026-07-02) ：委托到通用版 gov_price_etl.parse_price.is_price_valid。
    逻辑同源，单一权威。

    返回 True 表示文档价格有效。
    """
    from gov_price_etl.parse_price import is_price_valid as _is_valid
    return _is_valid(
        price_min=d.get("price_min"),
        price_max=d.get("price_max"),
        price=d.get("price"),
        tax_price=d.get("tax_price"),
        tax_min=d.get("tax_min"),
    )


def _source_to_dws(d: dict) -> dict:
    """DWD source → DWS doc：转换 attr 字段，清理空值。"""
    dws_doc = dict(d)
    attr = build_attr(dws_doc)
    dws_doc["attr"] = flat_attr_to_nested(attr)
    # 删除原顶层 attr_* 字段（已迁移到 attr nested）
    for f in list(dws_doc.keys()):
        if f.startswith("attr_"):
            dws_doc.pop(f)
    # 过滤空 date 字段（空字符串无法解析为 date 类型）
    for f in ("date", "publish_time"):
        if not dws_doc.get(f):
            dws_doc.pop(f, None)
    return dws_doc


# ── 阶段 2: 本地规则库解析 ──────────────────────────────────────────────
# 2026-07-18: catch-all 拦截已下放到 parse_spec/base.py (CATCH_ALL_KEYS)
# 本文件 dedup 只处理描述字段去重，数值字段不去重

# 数值字段（不去重）—— 即使 width=240 + length=240 数字相同，语义不同也不能合并
_NUMERIC_ATTR_KEYS = frozenset({
    "wall_thickness", "core_count", "thickness",
    "diameter", "outer_diameter", "inner_diameter",
    "length", "width", "height", "voltage", "pressure",
    "cross_section", "cross_section_area", "ring_stiffness", "fiber_core",
    "channels", "doors", "current", "temperature", "output",
    "spec_volume", "weight",
})
# 描述字段（catch-all 同值去重）—— type/grade/material/spec/note 同值只保留一个
_DESC_ATTR_KEYS = frozenset({
    "material", "type", "grade", "spec", "note", "feature", "usage",
    "series", "model", "color", "surface", "form",
    "fire_rating", "ip_rating", "drain_type", "inlet_type", "installation_type",
})


def _dedup_attr_by_spec_value(attrs: dict, spec: str) -> dict:
    """v0.7+:同值多 attr 去重。

    场景:纯文字 spec (如"珍珠岩"、"综合")被多个 catch-all 规则填到 type/grade/material,
    但正确归属只该是一个。这种数据冗余要清理掉,避免下游看板分类错误。

    2026-07-18 改造:
      - 数值字段（width/height/thickness/length/diameter...）不去重——
        即使多个 attr 的 value 数字相同（如 width=240 + length=240）,
        语义不同也不能合并。
      - 描述字段（type/grade/material/spec/note...）才去重——
        catch-all 同值时按业务优先级保留 1 个。

    2026-07-19 P0 改造 (脏率从 26.5% → 5% 以下):
      - brand 黑名单：单字母或强度等级前缀字母（M/C/P/PC/PO/S/SB/AC/PA/PP/PE/PVC）
        误被识别为 brand 时直接丢弃。
      - 三段式尺寸 spec 精确分配：识别 "X*Y*Z" 这种砖/板类 spec 模式，
        按位置（宽×高×厚）分配，删除多余的 diameter/length。

    描述字段优先级顺序（业务约定）:
      material > grade > type > spec > note > 其他描述字段

    Args:
        attrs: 解析出的 {attr: value} 字典
        spec: 原始 spec 字符串

    Returns:
        去重后的 {attr: value} 字典
    """
    if not attrs:
        return attrs
    attrs = dict(attrs)  # 不修改原 dict

    # P0-26: 特定 spec 模式补漏 (P5 补 2026-07-19)
    # 必须在 P0-1 之前,避免被 early return 截
    import re as _re
    _spec0 = (spec or "").strip()
    mP130_0 = _re.match(r"^P(\d+)$", _spec0)
    if mP130_0:
        if "brand" in attrs: del attrs["brand"]
        attrs["grade"] = f"P{mP130_0.group(1)}"
        return attrs
    mSN_0 = _re.match(r"^[Ss][Nn]\d+/[Ss]?[Nn]?\d+$", _spec0)
    if mSN_0:
        if "brand" in attrs: del attrs["brand"]
        attrs["model"] = mSN_0.group(0)
        return attrs
    mAC_0 = _re.match(r"^AC[-—\s]+(\d+)$", _spec0)
    if mAC_0:
        for k in ("pressure", "type", "brand"):
            if k in attrs: del attrs[k]
        attrs["grade"] = f"AC-{mAC_0.group(1)}"
        return attrs

    # P0-1: brand 黑名单（防 M32.5 → brand=M 这种情况）
    _BRAND_BLACKLIST = {
        "m", "c", "p", "pc", "po", "s", "sb", "sbs", "ac",
        "pa", "pp", "pe", "pvc", "pom", "abs", "pa6", "pp-r",
        # 中文 grade/type 误被识别为 brand (2026-07-19 P1 审计追加)
        "a级", "b级", "c级", "d级", "e级", "f级",
        "n类", "p类", "b类", "a类", "m类",
        "u型", "v型", "h型", "t型", "l型", "z型", "o型",
        "一等品", "优等品", "合格品", "正品", "副品",
        "厚", "薄", "标准", "非标",
    }
    if "brand" in attrs:
        bv = str(attrs["brand"]).lower().strip()
        # 中文双字品牌（海螺/冀东/盾石）是合法的，只对纯 ASCII 字母做长度限制
        is_ascii_letters = bool(bv) and all(ch.isascii() and ch.isalpha() for ch in bv)
        if bv in _BRAND_BLACKLIST or (is_ascii_letters and len(bv) <= 2):
            del attrs["brand"]

    if len(attrs) <= 1 or not spec:
        return attrs

    from collections import defaultdict
    # 按值分组: 同值 attr 聚到一起
    val_to_attrs = defaultdict(list)
    for k, v in attrs.items():
        val_to_attrs[v].append(k)

    desc_priority = [
        'material', 'grade', 'type', 'spec', 'note',
        'feature', 'usage', 'series', 'model', 'color', 'surface', 'form',
    ]

    cleaned = {}
    for v, ks in val_to_attrs.items():
        if len(ks) == 1:
            cleaned[ks[0]] = v
        else:
            # 2026-07-18: 拆分数值字段 vs 描述字段
            numeric_ks = [k for k in ks if k in _NUMERIC_ATTR_KEYS]
            desc_ks = [k for k in ks if k in _DESC_ATTR_KEYS]
            other_ks = [k for k in ks if k not in _NUMERIC_ATTR_KEYS and k not in _DESC_ATTR_KEYS]

            # 数值字段全部保留（不去重）
            for k in numeric_ks:
                cleaned[k] = v
            # 描述字段按优先级去重保留 1 个
            if desc_ks:
                kept = None
                for p in desc_priority:
                    if p in desc_ks:
                        kept = p
                        break
                if not kept:
                    kept = desc_ks[0]
                cleaned[kept] = v
            # 其他字段全部保留（未知 key 不去重，避免误丢）
            for k in other_ks:
                cleaned[k] = v

    # P0-2~6: 尺寸 spec 精确分配 (2026-07-19 P0+ 升级)
    # 覆盖：三段式带单位/前缀、二段式、单值带电气单位、单值带长度单位
    import re

    # 提取 spec 中的数字和单位
    spec_stripped = (spec or "").strip()

    # P0-23: pressure == strength 同值 dedup (全局,任何 P0 路径后)
    if (cleaned.get("pressure") and cleaned.get("strength") and
        cleaned["pressure"] == cleaned["strength"]):
        del cleaned["strength"]

    # P0-27: 全局 dedup (P5 补 2026-07-19) — 27a/c/d 在此, 27b 移后
    # 27a: model == power → 删 model (灯具 36W/LED12W)
    if cleaned.get("model") and cleaned.get("power") and cleaned["model"] == cleaned["power"]:
        del cleaned["model"]
    # 27c: weight == strength → 删 strength (160kg/m³ 等密度类)
    if cleaned.get("weight") and cleaned.get("strength") and cleaned["weight"] == cleaned["strength"]:
        del cleaned["strength"]
    # 27d: pressure == strength → 删 strength (32.5MPa 等)
    if cleaned.get("pressure") and cleaned.get("strength") and cleaned["pressure"] == cleaned["strength"]:
        del cleaned["strength"]

    # P0-11: H 型钢 "H N*N*N*N"（4 个数字 = 高×宽×腹板厚×翼缘厚） — 必须在 P0-2 之前
    mH = re.match(
        r"^[Hh]\s*(\d+(?:\.\d+)?)\s*[\*×x]\s*(\d+(?:\.\d+)?)\s*[\*×x]\s*(\d+(?:\.\d+)?)\s*[\*×x]\s*(\d+(?:\.\d+)?)",
        spec_stripped
    )
    if mH:
        h, w, t1, t2 = mH.group(1), mH.group(2), mH.group(3), mH.group(4)
        # H 型钢：直径/长度不该出现
        cleaned = {k: v for k, v in cleaned.items()
                   if k not in ("diameter", "length", "outer_diameter", "inner_diameter", "volume")}
        if "height" in cleaned:    cleaned["height"]    = f"{h}mm"
        if "width" in cleaned:     cleaned["width"]     = f"{w}mm"
        if "thickness" in cleaned: cleaned["thickness"] = f"{t1}mm"
        # 2026-07-19 P0-24: 第 4 数字 = 翼缘厚
        cleaned["flange_thickness"] = f"{t2}mm"
        return cleaned

    # P0-9: DN(N) 环刚度 "DN300(SN8)" / "DN500(SN12.5)" — 必须在 P0-2/3 之前
    mDN = re.match(
        r"^[Dd][Nn](\d+(?:\.\d+)?)\s*\(([A-Za-z]+\d*(?:\.\d+)?|[A-Za-z]+)\)\s*$",
        spec_stripped
    )
    if mDN:
        d, stiffness = mDN.group(1), mDN.group(2)
        cleaned = {k: v for k, v in cleaned.items()
                   if k not in ("width", "height", "thickness", "length",
                                "outer_diameter", "inner_diameter", "volume",
                                "package_type", "model")}
        if "diameter" in cleaned:    cleaned["diameter"]    = f"{d}mm"
        if "ring_stiffness" in cleaned: cleaned["ring_stiffness"] = stiffness
        return cleaned

    # P0-8: 钢管外径×壁厚 "ΦN*N" — 必须在 P0-3 之前
    mPhi = re.match(
        r"^[Φφ]\s*(\d+(?:\.\d+)?)\s*[\*×x]\s*(\d+(?:\.\d+)?)\s*(mm)?\s*$",
        spec_stripped
    )
    if mPhi:
        od, wt = mPhi.group(1), mPhi.group(2)
        unit = mPhi.group(3) or "mm"
        cleaned = {k: v for k, v in cleaned.items()
                   if k not in ("width", "height", "length",
                                "outer_diameter", "inner_diameter", "volume")}
        if "diameter" in cleaned:   cleaned["diameter"]   = f"{od}{unit}"
        if "thickness" in cleaned:  cleaned["thickness"]  = f"{wt}{unit}"
        return cleaned

    # P0-17: D 单字母前缀 "D22*2" (无缝钢管) — 必须在 P0-7 之前
    mD = re.match(
        r"^D\s*(\d+(?:\.\d+)?)\s*[\*×x]\s*(\d+(?:\.\d+)?)\s*(mm)?\s*$",
        spec_stripped
    )
    if mD:
        od, wt = mD.group(1), mD.group(2)
        unit = mD.group(3) or "mm"
        cleaned = {k: v for k, v in cleaned.items()
                   if k not in ("width", "height", "length",
                                "outer_diameter", "inner_diameter", "volume")}
        cleaned["diameter"]  = f"{od}{unit}"
        cleaned["thickness"] = f"{wt}{unit}"
        return cleaned

    # P0-7: 管件 "dnN*N" / "DeN*N" — 必须在 P0-3 之前
    mDn = re.match(
        r"^[Dd][nNeE]\s*(\d+(?:\.\d+)?)\s*[\*×x]\s*(\d+(?:\.\d+)?)\s*(mm)?\s*$",
        spec_stripped
    )
    if mDn:
        d1, d2 = mDn.group(1), mDn.group(2)
        unit = mDn.group(3) or "mm"
        cleaned = {k: v for k, v in cleaned.items()
                   if k not in ("width", "height", "thickness", "length",
                                "outer_diameter", "inner_diameter", "volume")}
        if "diameter" in cleaned: cleaned["diameter"] = f"{d1}{unit}"
        return cleaned

    # P0-12: 二段式 + 中文质量/表面后缀 "N*N优等品" "N*N光面" — 必须在 P0-3 之前
    m2q = re.match(
        r"^(\d+(?:\.\d+)?)\s*[\*×x]\s*(\d+(?:\.\d+)?)\s*"
        r"(优等品|一等品|合格品|正品|副品|光面|火烧面|拉丝|抛光|覆膜|磨砂)\s*$",
        spec_stripped
    )
    if m2q:
        a, b = m2q.group(1), m2q.group(2)
        unit = "mm"
        cleaned = {k: v for k, v in cleaned.items()
                   if k not in ("thickness", "diameter", "length",
                                "outer_diameter", "inner_diameter", "volume")}
        if a == b:
            if "width" in cleaned: cleaned["width"] = f"{a}{unit}"
        else:
            if "width" in cleaned:  cleaned["width"]  = f"{a}{unit}"
            if "height" in cleaned: cleaned["height"] = f"{b}{unit}"
        return cleaned

    # P0-13: 三段式 + 中文后缀 "N*N*N光面" "N*N*N优等品" — 必须在 P0-2 之前
    m3q = re.match(
        r"^(\d+(?:\.\d+)?)\s*[\*×x]\s*(\d+(?:\.\d+)?)\s*[\*×x]\s*(\d+(?:\.\d+)?)\s*"
        r"(优等品|一等品|合格品|正品|副品|光面|火烧面|拉丝|抛光|覆膜|磨砂|（覆膜）)\s*$",
        spec_stripped
    )
    if m3q:
        a, b, c = m3q.group(1), m3q.group(2), m3q.group(3)
        unit = "mm"
        cleaned = {k: v for k, v in cleaned.items()
                   if k not in ("diameter", "length", "outer_diameter",
                                "inner_diameter", "volume", "thickness", "width", "height", "volume")}
        # 2026-07-19 P0-19: 5xxx 系列铝合金 (6063/6061) - 删 diameter/thickness/width/height
        if re.match(r"^60\d{2}", spec_stripped):
            cleaned = {k: v for k, v in cleaned.items()
                       if k not in ("diameter", "thickness", "width", "height", "volume", "length")}
        if a == b:
            if "width" in cleaned: cleaned["width"] = f"{a}{unit}"
        else:
            if "width" in cleaned:  cleaned["width"]  = f"{a}{unit}"
            if "height" in cleaned: cleaned["height"] = f"{b}{unit}"
        if "thickness" in cleaned: cleaned["thickness"] = f"{c}{unit}"
        return cleaned

    # P0-14: 二段式 + 英寸/分数 "N*N/N″" "N*N″" (内丝三通) — 必须在 P0-3 之前
    m2in = re.match(
        r"^(\d+(?:\.\d+)?)\s*[\*×x]\s*(\d+(?:/\d+)?)\s*(″|" + chr(34) + "|" + chr(39) + chr(39) + "|" + chr(39) + "|英寸)\s*$",
        spec_stripped
    )
    if m2in:
        a, b = m2in.group(1), m2in.group(2)
        cleaned = {k: v for k, v in cleaned.items()
                   if k not in ("thickness", "length", "width", "height",
                                "outer_diameter", "inner_diameter", "volume")}
        if "diameter" in cleaned: cleaned["diameter"] = f"{a}mm"
        return cleaned

    # P0-15: 单值带"厚"+后缀 "30mm厚光面" — 必须在 P0-10 之前
    mThickSuf = re.match(
        r"^(\d+(?:\.\d+)?)\s*(mm|cm|m)\s*厚\s*(优等品|一等品|合格品|正品|副品|光面|火烧面|拉丝|抛光|覆膜|磨砂)\s*$",
        spec_stripped, re.IGNORECASE
    )
    if mThickSuf:
        val = mThickSuf.group(1) + mThickSuf.group(2)
        suf = mThickSuf.group(3)
        geo_keys = {"width", "height", "length", "diameter", "outer_diameter",
                    "inner_diameter", "volume"}
        if "thickness" in cleaned:
            cleaned["thickness"] = val
        for k in list(cleaned.keys()):
            if k in geo_keys and k != "thickness":
                del cleaned[k]
        if "surface" in cleaned:
            cleaned["surface"] = suf
        for k in list(cleaned.keys()):
            v = str(cleaned.get(k, "")).strip()
            if v in ("厚", "薄", "标准", "非标"):
                del cleaned[k]
        return cleaned

    # P0-16: 负号前缀 "-4*40" (扁钢) — 必须在 P0-3 之前
    mNeg = re.match(
        r"^-(\d+(?:\.\d+)?)\s*[\*×x]\s*(\d+(?:\.\d+)?)\s*(mm)?\s*$",
        spec_stripped
    )
    if mNeg:
        a, b = mNeg.group(1), mNeg.group(2)
        unit = mNeg.group(3) or "mm"
        cleaned = {k: v for k, v in cleaned.items()
                   if k not in ("diameter", "length",
                                "outer_diameter", "inner_diameter", "volume")}
        if "thickness" in cleaned: cleaned["thickness"] = f"{a}{unit}"
        if "width" in cleaned:     cleaned["width"]     = f"{b}{unit}"
        return cleaned

    # P0-18: PHC管桩型号 "400AB95" "400A95" (hainan 24 cases) — 必须在 P0-2 之前
    mPHC = re.match(
        r"^\d+[A-Z]+\d+$",
        spec_stripped
    )
    if mPHC:
        cleaned = {k: v for k, v in cleaned.items()
                   if k not in ("diameter", "thickness", "width", "height",
                                "length", "outer_diameter", "inner_diameter", "volume")}
        cleaned["model"] = mPHC.group(0)
        return cleaned

    # P0-21: 三段式 + 尾随 Q 等级 "N*N*NQ" (角钢) — 必须在 P0-2 之前
    m3qEnd = re.match(
        r"^(\d+(?:\.\d+)?)\s*[\*×x]\s*(\d+(?:\.\d+)?)\s*[\*×x]\s*(\d+(?:\.\d+)?)\s*(Q\d+[A-Z]?)\s*$",
        spec_stripped
    )
    if m3qEnd:
        a, b, c, qgrade = m3qEnd.group(1), m3qEnd.group(2), m3qEnd.group(3), m3qEnd.group(4)
        unit = "mm"
        cleaned = {k: v for k, v in cleaned.items()
                   if k not in ("diameter", "length", "outer_diameter",
                                "inner_diameter", "volume")}
        if a == b:
            if "width" in cleaned: cleaned["width"] = f"{a}{unit}"
            if "height" in cleaned: del cleaned["height"]
        else:
            if "width" in cleaned:  cleaned["width"]  = f"{a}{unit}"
            if "height" in cleaned: cleaned["height"] = f"{b}{unit}"
        cleaned["thickness"] = f"{c}{unit}"
        cleaned["material"]  = qgrade
        return cleaned

    # P0-22: 三段式 + 尾随 # 等级 "N*N*NN#" (砼空心砌块) — 必须在 P0-2 之前
    # 注：3rd 数字限 1-2 位 (避免 19050 这种 4 位数被错拆)
    m3hash = re.match(
        r"^(\d+(?:\.\d+)?)\s*[\*×x]\s*(\d+(?:\.\d+)?)\s*[\*×x]\s*(\d{1,2})\s*#\s*$",
        spec_stripped
    )
    if m3hash:
        a, b, c = m3hash.group(1), m3hash.group(2), m3hash.group(3)
        unit = "mm"
        cleaned = {k: v for k, v in cleaned.items()
                   if k not in ("diameter", "length", "outer_diameter",
                                "inner_diameter", "volume")}
        if a == b:
            if "width" in cleaned: cleaned["width"] = f"{a}{unit}"
            if "height" in cleaned: del cleaned["height"]
        else:
            if "width" in cleaned:  cleaned["width"]  = f"{a}{unit}"
            if "height" in cleaned: cleaned["height"] = f"{b}{unit}"
        cleaned["thickness"] = f"{c}{unit}"
        cleaned["grade"]     = "#"  # 标记为等级,具体值需 breed context
        return cleaned

    # P0-19: 6063-T5 铝合金型材 (hainan 7 cases) — 必须在 P0-2 之前
    m6063 = re.match(
        r"^60\d{2}-T\d+$",
        spec_stripped
    )
    if m6063:
        cleaned = {k: v for k, v in cleaned.items()
                   if k not in ("diameter", "thickness", "width", "height",
                                "length", "outer_diameter", "inner_diameter", "volume")}
        return cleaned

    # P0-27b: diameter == thickness → 删 diameter (H型钢/玻璃/排水板, 必须在 P0-7~22 之后)
    if cleaned.get("diameter") and cleaned.get("thickness") and cleaned["diameter"] == cleaned["thickness"]:
        del cleaned["diameter"]

    # P0-2: 三段式 "X*Y*Z"（允许前缀文字和后缀单位）
    # 例: "200*95*53" / "600*600*0.8mm" / "Q235B 50*50*5mm" / "2440*1220*18"
    m3 = re.match(
        r"^(?:[A-Za-z0-9_\-\u4e00-\u9fa5]+\s+)?"
        r"(\d+(?:\.\d+)?)\s*[\*×x]\s*"
        r"(\d+(?:\.\d+)?)\s*[\*×x]\s*"
        r"(\d+(?:\.\d+)?)\s*"
        r"(mm|cm|m|[\u338d-\u338f])?\s*$",
        spec_stripped
    )
    if m3:
        a, b, c = m3.group(1), m3.group(2), m3.group(3)
        unit = m3.group(4) or "mm"
        # 砖/板/瓦类只有 3 个尺寸字段，diameter/length/volume 不该出现
        cleaned = {k: v for k, v in cleaned.items()
                   if k not in ("diameter", "length", "outer_diameter",
                                "inner_diameter", "volume")}
        if "width" in cleaned:     cleaned["width"]     = f"{a}{unit}"
        if "height" in cleaned:    cleaned["height"]    = f"{b}{unit}"
        if "thickness" in cleaned: cleaned["thickness"] = f"{c}{unit}"
        # 2026-07-19 P0++: 首二数相等 → 删 height
        if a == b and "width" in cleaned and "height" in cleaned:
            del cleaned["height"]
        # 2026-07-19 P0-25: 第二三数相等 → 删 thickness (如 600*200*200)
        if b == c and "height" in cleaned and "thickness" in cleaned:
            del cleaned["thickness"]
        # 2026-07-19 P0++: 尾随 Q\d+ 等级 (如 40*40*4Q235) → 删 diameter, 抓 grade
        if re.search(r"Q\d+[A-Z]?$", spec_stripped):
            if "diameter" in cleaned: del cleaned["diameter"]
            if "length" in cleaned:   del cleaned["length"]
            qm = re.search(r"Q\d+[A-Z]?", spec_stripped)
            if qm and "material" in cleaned:
                cleaned["material"] = qm.group(0)
        # 2026-07-19 P0++: 尾随 # 等级 (如 390*240*19050#) → 删 diameter
        if re.search(r"\d+#$", spec_stripped):
            if "diameter" in cleaned: del cleaned["diameter"]
            if "length" in cleaned:   del cleaned["length"]
        return cleaned

    # P0-3: 二段式 "X*Y"（例: "200*200" / "400*150" / "3*12"）
    m2 = re.match(
        r"^(\d+(?:\.\d+)?)\s*[\*×x]\s*(\d+(?:\.\d+)?)\s*(mm|cm|m)?\s*$",
        spec_stripped
    )
    if m2:
        a, b = m2.group(1), m2.group(2)
        unit = m2.group(3) or "mm"
        # 2 段是 长×宽 或 宽×高，diameter/thickness/volume 不该出现
        cleaned = {k: v for k, v in cleaned.items()
                   if k not in ("diameter", "thickness", "outer_diameter",
                                "inner_diameter", "volume")}
        if "length" in cleaned and "width" in cleaned:
            cleaned["length"] = f"{a}{unit}"
            cleaned["width"]  = f"{b}{unit}"
        elif "width" in cleaned and "height" in cleaned:
            cleaned["width"]  = f"{a}{unit}"
            cleaned["height"] = f"{b}{unit}"
        elif "width" in cleaned:
            cleaned["width"] = f"{a}{unit}"
        # 2026-07-19 P0++: 二段式首二数相等 (如 200*200) → width=height 同值
        # 保留 width，删除 height 避免同值多 attr
        if a == b and "width" in cleaned and "height" in cleaned:
            del cleaned["height"]
        return cleaned

    # P0-4: 单值带电气单位 W/V/A/kV/MPa（例: "400W" / "200A" / "220V"）
    m1e = re.match(
        r"^(\d+(?:\.\d+)?)\s*(W|kW|V|kV|A|mA|MPa|kPa|bar|kg|t|g|l|mol)$",
        spec_stripped, re.IGNORECASE
    )
    if m1e:
        val = m1e.group(1) + m1e.group(2)
        # model 保留（型号就是这个数值+单位），删 diameter/length/thickness/width/height/volume
        cleaned = {k: v for k, v in cleaned.items()
                   if k not in ("diameter", "length", "thickness", "width",
                                "height", "outer_diameter", "inner_diameter", "volume")}
        # 如果 model/power 存在，正确写入
        if "model" in cleaned:  cleaned["model"]  = val
        if "power" in cleaned:  cleaned["power"]  = val
        if "voltage" in cleaned and m1e.group(2).lower() in ("v", "kv"):  cleaned["voltage"] = val
        if "current" in cleaned and m1e.group(2).lower() in ("a", "ma"):  cleaned["current"] = val
        if "pressure" in cleaned and m1e.group(2).lower() in ("mpa", "kpa", "bar"):  cleaned["pressure"] = val
        return cleaned

    # P0-10: 单值带长度单位+厚 "Nmm厚"（例: "1.0mm厚" / "5mm厚"）
    mThick = re.match(
        r"^(\d+(?:\.\d+)?)\s*(mm|cm|m|[\u338d-\u338f])\s*厚\s*$",
        spec_stripped, re.IGNORECASE
    )
    if mThick:
        val = mThick.group(1) + mThick.group(2)
        geo_keys = {"width", "height", "length", "diameter", "outer_diameter",
                    "inner_diameter", "volume"}
        keep_one = None
        if "thickness" in cleaned:
            keep_one = "thickness"; cleaned["thickness"] = val
        elif "width" in cleaned:
            keep_one = "width"; cleaned["width"] = val
        elif "diameter" in cleaned:
            keep_one = "diameter"; cleaned["diameter"] = val
        for k in list(cleaned.keys()):
            if k in geo_keys and k != keep_one:
                del cleaned[k]
        # 清理“厚”词尾残留（不这该出现在任何字段中）
        for k in list(cleaned.keys()):
            v = str(cleaned.get(k, "")).strip()
            if v in ("厚", "薄", "标准", "非标"):
                del cleaned[k]
        return cleaned

    # P0-20: 密度 Nkg/m³ (jilin 2 cases) — 必须在 P0-5 之前
    mDensity = re.match(
        r"^(\d+)\s*kg/m[3³³]$",
        spec_stripped, re.IGNORECASE
    )
    if mDensity:
        val = mDensity.group(1) + "kg/m³"
        geo_keys = {"width", "height", "length", "diameter", "outer_diameter",
                    "inner_diameter", "volume", "thickness"}
        for k in list(cleaned.keys()):
            if k in geo_keys:
                del cleaned[k]
        if "density" in cleaned:
            cleaned["density"] = val
        return cleaned

    # P0-5: 单值带长度单位 mm/cm/m（例: "5mm" / "300mm" / "10cm"）
    m1l = re.match(
        r"^(\d+(?:\.\d+)?)\s*(mm|cm|m|[\u338d-\u338f])$",
        spec_stripped, re.IGNORECASE
    )
    if m1l:
        val = m1l.group(1) + m1l.group(2)
        # 单值 spec 只该有 1 个几何属性，保留 thickness（最常见），删其他几何类
        if "thickness" in cleaned:
            cleaned["thickness"] = val
        elif "width" in cleaned:
            cleaned["width"] = val
        elif "diameter" in cleaned:
            cleaned["diameter"] = val
        # 删多余几何字段（model/grade/material 不在集合里，不动）
        geo_keys = {"width", "height", "length", "diameter", "outer_diameter",
                    "inner_diameter", "volume"}
        # 保留 priority 1 的，删其他
        keep_one = None
        for p in ("thickness", "width", "diameter", "height", "length"):
            if p in cleaned:
                keep_one = p
                break
        for k in list(cleaned.keys()):
            if k in geo_keys and k != keep_one:
                del cleaned[k]
        return cleaned

    # P0-6: 单值无单位（例: "300" / "50"） → 视为型号/代号，保留 model
    m1n = re.match(
        r"^(\d+(?:\.\d+)?)$",
        spec_stripped
    )
    if m1n:
        val = m1n.group(1)
        # 删多余几何字段，保留 model/power/grade 等描述字段
        if "model" in cleaned:
            cleaned["model"] = val
        for k in ("width", "height", "length", "diameter", "outer_diameter",
                  "inner_diameter", "thickness", "volume"):
            if k in cleaned:
                del cleaned[k]
        return cleaned

    return cleaned


def _parse_spec_local(spec: str, breed: str, category: str, city: str,
                        l3: str = "") -> dict:
    """阶段 2:本地规则库 breed_spec_rules.db 解析(不调 AI)。

    v0.7:加 l3 参数(类目分级,如"建筑玻璃" / "焊接与切割材料"),
    透传到 parser.parse() 用于 vector_store 召回加权(+0.40 最高优先级)。
    v0.7+:末尾加 _dedup_attr_by_spec_value 清理同值多 attr 冗余。
    v0.8+ (2026-07-18): 移除 filter_by_l3_whitelist 调用（白名单生成逻辑有 bug,
    会误过滤掉 width/height/thickness 等数值字段。catch-all 拦截已下放 parser 层）。

    Returns:
        {attr_name: value, ...} 或 {}(未命中)
    """
    if not spec:
        return {}
    parser = get_parser(city)
    if not parser:
        return {}
    try:
        parsed = parser.parse(spec, breed, category, l3)
        # v0.8+ (2026-07-18): 移除白名单过滤，避免误过滤数值字段
        # v0.7+: dedup 仅对描述字段去重（数值字段不去重）
        parsed = _dedup_attr_by_spec_value(parsed, spec)
        return {k: v for k, v in parsed.items() if v}
    except Exception:
        return {}


# ── 阶段 3: AI 串行解析 ─────────────────────────────────────────────────
def _ai_parse_specs_serial(items: list, city: str) -> dict:
    """阶段 3：AI batch_spec_parse 串行批次解析。

    Args:
        items: [{"spec", "breed", "category", "doc_id"}, ...]
        city:  城市 key（缓存分区用）

    Returns:
        {doc_id: (attrs_dict, source)}，source ∈ {'ai', 'ai_fallback'}
    """
    if not items:
        return {}

    from gov_price_etl.ai.service import parse_spec_batch

    # 按 (breed, spec) 去重，减少 AI 调用量
    groups: dict = defaultdict(list)
    for it in items:
        key = (it["breed"], it["spec"])
        groups[key].append(it)
    deduped = [v[0] for v in groups.values()]
    print(f"    [STG3 AI] 调用 batch_spec_parse: {len(items)} → {len(deduped)} (去重)")

    # 串行批次（每批 AI_PARSE_BATCH_SIZE 条）
    all_results: list = []
    total_batches = (len(deduped) + AI_PARSE_BATCH_SIZE - 1) // AI_PARSE_BATCH_SIZE
    t_stage3 = time.time()
    for i in range(0, len(deduped), AI_PARSE_BATCH_SIZE):
        batch_idx = i // AI_PARSE_BATCH_SIZE + 1
        chunk = deduped[i:i + AI_PARSE_BATCH_SIZE]
        chunk_items = [{"spec": it["spec"], "breed": it["breed"],
                        "category": it["category"],
                        "l3": it.get("category_l3", "")}  # v0.7+: L3 透传到 AI 解析与入库
                       for it in chunk]
        t0 = time.time()
        try:
            chunk_results = parse_spec_batch(chunk_items, write_rules=True)
            all_results.extend(chunk_results)
            print(f"    [STG3 AI] 批次 {batch_idx}/{total_batches}: {len(chunk)} 条，{time.time()-t0:.1f}s")
        except Exception as e:
            print(f"    [STG3 AI] 批次 {batch_idx}/{total_batches} 失败 ({time.time()-t0:.1f}s): {e}")
            # 失败：占位失败结果
            for it in chunk:
                all_results.append({
                    "spec": it["spec"],
                    "ok": False,
                    "suggestions": [],
                    "failed_reason": str(e),
                })
        if i + AI_PARSE_BATCH_SIZE < len(deduped):
            time.sleep(AI_PARSE_BATCH_SLEEP_S)
    print(f"    [STG3 AI] 阶段 3 AI 解析总耗时 {time.time()-t_stage3:.1f}s")

    # 把 AI 建议执行 code_block 提取 attr
    # v0.14 (2026-07-22):保留每条 result 的 ok / failed_reason,供下游 _flush_ai_batch_to_dws
    # 给 DWS 文档打 ai_ok / ai_failed_reason audit 标签。
    results_map: dict = {}  # spec → 完整 result {ok, suggestions, failed_reason, ...}
    for r in all_results:
        results_map[r.get("spec", "")] = r

    out: dict = {}
    for it in items:
        r = results_map.get(it["spec"], {}) or {}
        ok = bool(r.get("ok", False))
        suggestions = r.get("suggestions", []) or []
        failed_reason = r.get("failed_reason", "") or ""
        attrs = _execute_suggestions(suggestions, it["spec"])
        if attrs:
            out[it["doc_id"]] = (attrs, "ai", ok, failed_reason)
        else:
            out[it["doc_id"]] = ({}, "ai_fallback", ok, failed_reason)
    return out


def _execute_suggestions(suggestions: list, spec: str) -> dict:
    """执行 AI 返回的建议列表，提取 attr dict。"""
    attrs: dict = {}
    for s in suggestions:
        if not isinstance(s, dict):
            continue
        a = s.get("attr", "")
        c = s.get("code_block", "")
        if not a or not c:
            continue
        norm_a = a[5:] if a.startswith("attr_") else a
        try:
            exec_globals = {"result": {}, "re": re, "s": spec}
            code = c if isinstance(c, str) else "\n".join(c)
            # Python 3.12+ 对字符串中 \s 等非标注义序列产生 SyntaxWarning,
            # Dify 返回的 code_block 含 raw string (r'...') 语义，
            # compile 后 warnings.filterwarnings 静默处理
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                exec(code, exec_globals)
            val = exec_globals.get("result", {}).get(norm_a, "")
            if not val:
                val = exec_globals.get("result", {}).get(a, "")
            if val:
                attrs[norm_a] = str(val)
        except Exception:
            pass
    return attrs


# ── 阶段 1+2+3 合并: DWD → DWS 三段式 ────────────────────────────────────
def _dwd_to_dws_three_stages(
    es_host: str,
    city: str,
    cfg: dict,
    *,
    batch_size: int = 500,
    category: str = "",
    dry_run: bool = False,
    with_ai: bool = True,  # v0.7+ bug fix: plain 模式传 False 跳过 stage 3,避免误清 attr_source
) -> Tuple[int, int, int, int]:
    """DWD → DWS 显式三段式。

    Returns:
        (stage1_synced, stage2_synced, stage3_synced, failed)
        - stage1_synced: DWD attr 非空直接同步
        - stage2_synced: 本地规则库命中同步
        - stage3_synced: AI 串行命中同步
    """
    dwd_idx = cfg["dwd"]
    dws_idx = cfg["dws"]
    session = get_es_client(es_host)

    # 防御：DWS == DWD 时（部分城市暂用同索引，如 henan），
    # 写入 DWS 会同时改 DWD 的 etl_time，导致 search_after 死循环。
    # 数据本就在同一个索引里，不需要再同步。
    if dwd_idx == dws_idx:
        cnt = 0
        try:
            cnt = session.post(
                f"{es_host}/{dwd_idx}/_count",
                json={"query": {"match_all": {}}},
                timeout=30,
            ).json().get("count", 0)
        except Exception:
            pass
        print(f"  [DWS+AI] {city}: DWD == DWS（{dwd_idx}），无需同步（{cnt} 条已是最终态）")
        return 0, 0, 0, 0

    if not dry_run:
        ensure_indices(es_host, cfg)

    # 启用 _id 字段排序支持
    try:
        requests.put(
            f"{es_host}/_cluster/settings",
            json={"persistent": {"indices.id_field_data.enabled": "true"}},
        )
    except Exception:
        pass

    # 查询条件：DWD spec 非空 + 可选 category 过滤
    must_clauses = [{"exists": {"field": "spec"}}]
    if category:
        must_clauses.append({"term": {"category": category}})

    # 统计总数
    cnt = session.post(f"{es_host}/{dwd_idx}/_count",
                       json={"query": {"bool": {"must": must_clauses}}}, timeout=30)
    total = cnt.json().get("count", 0) if cnt.status_code == 200 else 0
    if total == 0:
        print(f"  [DWS+AI] {city}: 无待同步数据")
        return 0, 0, 0, 0
    print(f"  [DWS+AI] {city}: {dwd_idx} → {dws_idx} ({total:,} 条)")

    stage1_synced = stage2_synced = stage3_synced = failed = pages = 0

    # 初次搜索
    body = {
        "query": {"bool": {"must": must_clauses}},
        "size": batch_size,
        "sort": [{"etl_time": "asc"}, {"_id": "asc"}],
    }
    resp = session.post(f"{es_host}/{dwd_idx}/_search", json=body, timeout=60)
    if resp.status_code != 200:
        print(f"  [DWS+AI] 查询 DWD 失败: {resp.text[:200]}")
        return 0, 0, 0, 0
    hits = resp.json()["hits"]["hits"]

    # 攒批容器
    ai_batch: list = []        # 阶段 3 待 AI 解析的 doc
    hits_by_id: dict = {}      # doc_id → hit（用于 AI 回写时找源文档）

    prev_etl_time = None

    while hits:
        pages += 1

        # 本轮攒批：阶段 1 同步 + 阶段 2 解析回写 + 阶段 3 攒批
        dws_docs_s1: list = []   # 阶段 1 同步
        dws_ids_s1: list = []
        dws_docs_s2: list = []   # 阶段 2 同步（已写回 DWD）
        dws_ids_s2: list = []
        dwd_update_s2: list = [] # 阶段 2 回写 DWD attr
        dwd_update_docs_s2: list = []

        for h in hits:
            doc_id = h["_id"]
            d = dict(h["_source"])
            hits_by_id[doc_id] = h
            # 价格过滤：price 和 tax_price 都为空/0 → 跳过（2026-06-24 道友需求）
            if not _is_price_valid(d):
                continue
            spec = d.get("spec", "")
            breed = d.get("breed", "")
            cat = d.get("category", "")

# v0.7: DWD 不再存 attr(transform_doc 写空 attr),
            # 阶段 1 (直通 etl) 取消,所有 doc 统一走解析路径。
            # ── 阶段 1 (原阶段 2): 本地规则库 breed_spec_rules.db 解析 ─────────────
            local_attrs = _parse_spec_local(spec, breed, cat, city,
                                                     l3=d.get("category_l3", ""))
            if local_attrs:
                nested = flat_attr_to_nested(local_attrs)
                dws_doc = _source_to_dws(d)
                dws_doc["attr"] = nested
                dws_doc["attr_source"] = "local_db"
                dws_docs_s2.append(dws_doc)
                dws_ids_s2.append(doc_id)
                continue

            # ── 阶段 2 (原阶段 3): 攒批送 AI 串行解析 ──────────────────────────────
            # v0.7+ bug fix: plain 模式 (with_ai=False) 跳过 stage 3,
            #   依赖 AI 才能解析的 spec 留在 DWD 不进 DWS (与"无 AI"语义一致)
            if with_ai:
                ai_batch.append({
                    "doc_id": doc_id, "spec": spec,
                    "breed": breed, "category": cat,
                    # v0.12+ (2026-07-18): 补 category_l3，透传到 chunk_items → service.py write_rules
                    # → db.breed_spec_rules.l3。之前缺这一项导致 db 141 条规则 l3 全空，
                    # 召回加权 +0.40 失效（vec_store.search l3 匹配分项工程最高加权）。
                    "category_l3": d.get("category_l3", ""),
                })

        # ── 批量写入 ─────────────────────────────────────────────────
        if dws_docs_s1:
            if dry_run:
                stage1_synced += len(set(dws_ids_s1))  # unique doc 数
            else:
                ok, err = bulk_index(es_host, dws_idx, dws_docs_s1, dws_ids_s1)
                stage1_synced += len(set(dws_ids_s1))  # unique doc 数
                failed += err

        if dws_docs_s2:
            if not dry_run and dwd_update_s2:
                # 写回 DWD attr
                update_body = "".join(dwd_update_s2)
                session.post(
                    f"{es_host}/{dwd_idx}/_bulk",
                    data=update_body.encode("utf-8"),
                    headers={"Content-Type": "application/x-ndjson"},
                    timeout=60,
                )
            if dry_run:
                stage2_synced += len(set(dws_ids_s2))  # unique doc 数
            else:
                ok, err = bulk_index(es_host, dws_idx, dws_docs_s2, dws_ids_s2)
                stage2_synced += len(set(dws_ids_s2))  # unique doc 数
                failed += err

        # AI batch 满了则触发串行解析 + 回写（plain 模式跳过）
        if with_ai and len(ai_batch) >= AI_PARSE_BATCH_SIZE * 5:  # 攒够 5 批就触发，避免攒太多
            stage3_synced += _flush_ai_batch_to_dws(
                es_host, city, dwd_idx, dws_idx,
                ai_batch, hits_by_id, dry_run
            )

        if pages % 20 == 0:
            print(f"    pages={pages}, s1={stage1_synced}, s2={stage2_synced}, s3={stage3_synced}/{total}")

        # search_after 翻页
        last_hit = hits[-1]
        last_etl_time = last_hit["_source"].get("etl_time", "") or ""
        body_page = {
            "query": {"bool": {"must": must_clauses}},
            "size": batch_size,
            "search_after": [last_etl_time, last_hit["_id"]],
            "sort": [{"etl_time": "asc"}, {"_id": "asc"}],
        }
        try:
            resp_page = session.post(f"{es_host}/{dwd_idx}/_search", json=body_page, timeout=60)
        except Exception:
            break
        if resp_page.status_code != 200:
            break
        hits = resp_page.json()["hits"]["hits"]
        for h in hits:
            hits_by_id[h["_id"]] = h
        if pages > 1 and hits and last_etl_time == prev_etl_time:
            print(f"  [WARN] search_after 可能死循环: etl_time={repr(last_etl_time)}, 强制退出", flush=True)
            break
        prev_etl_time = last_etl_time

    # 剩余 AI batch
    if with_ai and ai_batch:
        stage3_synced += _flush_ai_batch_to_dws(
            es_host, city, dwd_idx, dws_idx,
            ai_batch, hits_by_id, dry_run
        )

    print(
        f"  [DWS+AI] {city} 完成: "
        f"s1(etl)={stage1_synced}, s2(local_db)={stage2_synced}, s3(ai)={stage3_synced}, "
        f"failed={failed}"
    )
    return stage1_synced, stage2_synced, stage3_synced, failed


def _flush_ai_batch_to_dws(
    es_host: str, city: str, dwd_idx: str, dws_idx: str,
    ai_batch: list, hits_by_id: dict, dry_run: bool,
) -> int:
    """阶段 3 攒批触发：调 AI 串行解析 → 回写 DWD + 同步 DWS。"""
    if not ai_batch:
        return 0
    session = get_es_client(es_host)

    # 调 AI 串行批次解析
    ai_results = _ai_parse_specs_serial(ai_batch, city)

    dws_docs: list = []
    dws_ids: list = []
    dwd_update_body = ""
    for it in ai_batch:
        doc_id = it["doc_id"]
        # v0.14 (2026-07-22): 4 元组 (attrs, src, ai_ok, failed_reason)
        result = ai_results.get(doc_id)
        if result is None:
            attrs, src, ai_ok, reason = {}, "ai_fallback", False, "no_result_from_ai"
        else:
            attrs, src, ai_ok, reason = result
        h = hits_by_id.get(doc_id)
        if not h:
            continue
        # 价格过滤：price 和 tax_price 都为空/0 → 跳过（2026-06-24 道友需求）
        if not _is_price_valid(dict(h["_source"])):
            continue
        # v0.14 (2026-07-22) 调整（道友需求）：
        #   ok=false 也入 DWS。改前：AI 显式返失败 (src=="ai_fallback") 不入 DWS；现移除该 continue。
        #   改前：attrs 空也不入 DWS；现移除该 continue（DWD 已有 attr 也要保留入 DWS）。
        #   副作用：DWS 会有 attr=[] 但 ai_ok=false 的 doc，运营可按 ai_ok=false 过滤。
        src_doc = dict(h["_source"])
        # 合并 src nested attr（如已有顶层 attr_*）
        if not attrs:
            attrs = build_attr(src_doc)
        else:
            src_attr = src_doc.get("attr")
            if isinstance(src_attr, dict):
                for ak, av in src_attr.items():
                    if ak not in attrs:
                        attrs[ak] = av
            elif isinstance(src_attr, list):
                for item in src_attr:
                    if isinstance(item, dict):
                        ak = item.get("k", "")
                        av = item.get("v", "")
                        if ak and ak not in attrs:
                            attrs[ak] = str(av)

        # v0.7+: stage 3 AI 路径也要 dedup（如粉煤灰烧结砖 AI 解出 5 键含 length/diameter 同值）
        attrs = _dedup_attr_by_spec_value(attrs, src_doc.get("spec", ""))

        nested = flat_attr_to_nested(attrs)
        # 回写 DWD：只在 AI 成功 (ai_ok=true) 且 attrs 非空时回写。
        # 避免 ai_fallback 把空 attr 写回 DWD 污染源头。
        if attrs and ai_ok and not dry_run:
            dwd_update_body += (
                json.dumps({"update": {"_id": doc_id}}, ensure_ascii=False) + "\n" +
                json.dumps({"doc": {"attr": attrs}}, ensure_ascii=False) + "\n"
            )

        # 同步 DWS —— ai_fallback 也入，标 audit 字段供运营巡检
        # v0.13 (2026-07-22 之前) 拦截：attr=[] 会制造 DWS 孤儿；
        # v0.14 放开：attr 可能空（DWD 也没 attr 且 AI 也拒解析时），但 ai_ok=false 让其
        # 仍可见，避免"价格有效但 attr 解析失败的 doc"在 DWS 之外（dashboard 等下游读不到）。
        src_doc["attr"] = nested
        src_doc["attr_source"] = src
        src_doc["ai_ok"] = bool(ai_ok)
        if not ai_ok:
            # 限长 500 字符，防 LLM 长 msg 撑爆 ES storage
            src_doc["ai_failed_reason"] = (reason or "no_reason")[:500]
        for f in ("date", "publish_time"):
            if not src_doc.get(f):
                src_doc.pop(f, None)
        dws_docs.append(src_doc)
        dws_ids.append(doc_id)

    if not dry_run and dwd_update_body:
        session.post(
            f"{es_host}/{dwd_idx}/_bulk",
            data=dwd_update_body.encode("utf-8"),
            headers={"Content-Type": "application/x-ndjson"},
            timeout=60,
        )

    if dws_docs:
        if dry_run:
            ai_batch.clear()  # 清空攒批容器（避免重复送 AI）
            return len(set(dws_ids))  # unique doc 数
        ok, err = bulk_index(es_host, dws_idx, dws_docs, dws_ids)
        ai_batch.clear()  # 清空攒批容器（避免重复送 AI 和重复累加 s3）
        return len(set(dws_ids))  # unique doc 数
    ai_batch.clear()  # 即使 dws_docs 为空也要清空
    return 0


# ── 三个对外入口（薄壳，向后兼容） ─────────────────────────────────────
def sync_dws(es_host: str, city: str, cfg: dict, *,
             batch_size: int = 500, dry_run: bool = False,
             source_filter: Callable = None,
             enrich_attr: Callable = None) -> Tuple[int, int]:
    """DWD → DWS 同步核心循环（兼容旧 source_filter/enrich_attr 接口）。

    新代码推荐用 sync_dws_with_ai()，内部走三段式。
    """
    dwd_idx = cfg["dwd"]
    dws_idx = cfg["dws"]

    # 防御：DWS == DWD 时跳过（见 _dwd_to_dws_three_stages 注释）
    if dwd_idx == dws_idx:
        print(f"  [DWS] {city}: DWD == DWS（{dwd_idx}），无需同步")
        return 0, 0

    session = get_es_client(es_host)

    if not dry_run:
        ensure_indices(es_host, cfg)

    if source_filter is None:
        source_filter = lambda d, h: bool(d.get("spec"))

    body = {
        "query": {"match_all": {}},
        "size": batch_size,
        "sort": [{"etl_time": "asc"}, {"_id": "asc"}],
    }
    resp = session.post(f"{es_host}/{dwd_idx}/_search", json=body, timeout=60)
    if resp.status_code != 200:
        return 0, 0
    hits = resp.json()["hits"]["hits"]
    total_resp = session.post(f"{es_host}/{dwd_idx}/_count", json={"query": {"match_all": {}}}, timeout=30)
    total = total_resp.json().get("count", 0) if total_resp.status_code == 200 else 0
    if total == 0:
        return 0, 0

    synced = failed = skipped = pages = 0
    prev_etl_time = None
    while hits:
        pages += 1
        dws_docs, dws_ids = [], []
        for h in hits:
            d = dict(h["_source"])
            if not source_filter(d, h):
                skipped += 1
                continue
            # 价格过滤：price 和 tax_price 都为空/0 → 跳过（2026-06-24 道友需求）
            if not _is_price_valid(d):
                skipped += 1
                continue
            if enrich_attr is not None:
                new_attr = enrich_attr(d, h)
                if new_attr:
                    d["attr"] = flat_attr_to_nested(new_attr)
                elif not d.get("attr"):
                    d["attr"] = flat_attr_to_nested(build_attr(d))
            else:
                d = _source_to_dws(d)
            dws_docs.append(d)
            dws_ids.append(h["_id"])
        if dws_docs:
            if dry_run:
                synced += len(dws_docs)
            else:
                ok, err = bulk_index(es_host, dws_idx, dws_docs, dws_ids)
                synced += ok
                failed += err

        last_hit = hits[-1]
        last_etl_time = last_hit["_source"].get("etl_time", "") or ""
        body = {
            "query": {"match_all": {}},
            "size": batch_size,
            "sort": [{"etl_time": "asc"}, {"_id": "asc"}],
            "search_after": [last_etl_time, last_hit["_id"]],
        }
        try:
            resp = session.post(f"{es_host}/{dwd_idx}/_search", json=body, timeout=60)
        except Exception:
            break
        if resp.status_code != 200:
            break
        hits = resp.json()["hits"]["hits"]
        if pages > 1 and hits and last_etl_time == prev_etl_time:
            break
        prev_etl_time = last_etl_time

    return synced, failed


def sync_dws_plain(es_host: str, city: str, cfg: dict, batch_size: int = 500,
                   category: str = "", dry_run: bool = False) -> Tuple[int, int]:
    """DWD spec 非空 → DWS（不调 AI，对应旧 flush_to_dws）。

    v0.7+ bug fix: 旧实现走 legacy sync_dws(),会清空 attr_source 字段。
    现在改走三段式 + with_ai=False,保证 attr_source 不被覆盖。
    依赖 AI 的 spec 留在 DWD 不进 DWS（与"不调 AI"语义一致）。
    """
    s1, s2, s3, f = _dwd_to_dws_three_stages(
        es_host, city, cfg,
        batch_size=batch_size, category=category, dry_run=dry_run,
        with_ai=False,  # plain 模式 = 只走 stage 1 (etl) + stage 2 (local_db)
    )
    return (s1 + s2 + s3), f


def sync_dws_quick(es_host: str, city: str, cfg: dict, batch_size: int = 1000,
                   dry_run: bool = False) -> Tuple[int, int, int]:
    """DWD attr 非空 → DWS（不调 AI，对应旧 sync_dws_quick.py）。

    注：本接口等价于 sync_dws_with_ai 的"阶段 1"——只同步 attr 已有的。
    """
    def _filter(d, h):
        return bool(build_attr(d))
    s, f = sync_dws(es_host, city, cfg, batch_size=batch_size, dry_run=dry_run, source_filter=_filter)
    return s, 0, f


def sync_dws_with_ai(es_host: str, city: str, cfg: dict, batch_size: int = 500,
                     ai_batch_size: int = 100, category: str = "",
                     dry_run: bool = False) -> Tuple[int, int]:
    """DWD → DWS 三段式（对应旧 flush_to_dws_with_ai）。"""
    s1, s2, s3, f = _dwd_to_dws_three_stages(
        es_host, city, cfg,
        batch_size=batch_size, category=category, dry_run=dry_run,
    )
    return (s1 + s2 + s3), f
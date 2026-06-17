"""classify/utils.py - v2 L3 分类的公共工具

被以下调用方复用：
  1. scripts/ai_validate_l3_map.py — 全量 64 L3 校验 v1_translated
  2. gov_price_etl/ai/service.py:classify_v2_batch — ETL 阶段 3 增量分类

核心工具：
  - norm_bc()        智能引号 → 直引号（修复 AI Unicode 归一化导致 join 丢失）
  - format_l3_list() 把 64 L3 拼成 prompt 文本（防止 AI 拼段错误）
  - format_breed_list() 把品种列表拼成 prompt 文本
  - merge_ai_results() 把 AI 输出按 breed_clean 关联回原始 batch（支持归一化匹配）
  - validate_l3()    校验 suggested_l3 是否在 64 L3 全集里

⚠️ 这些工具存在的根本原因：scripts/ai_validate_l3_map.py 实际跑 4068 条时踩了 3 个坑：
  1. AI 拼 l3 为 5 段（"01.01.04.01.04.01"）→ format_l3_list 不拼段 + prompt 显式提示
  2. AI 把智能引号 "" 规范成 "" → norm_bc 归一化匹配
  3. AI 给的 l3 不在 64 L3 → validate_l3 合法性校验 + 丢弃
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple


# ── 1. breed_clean 归一化 ──────────────────────────────────────────
def norm_bc(s: str) -> str:
    """breed_clean 归一化：智能引号 → 直引号。

    AI 模型常会把 U+201C/U+201D（“”）规范成 ASCII 的 "（U+0022），
    导致 join 丢失。归一化后才能匹配上原始 batch。

    修复触发场景：scripts/ai_validate_l3_map.py 处理
      '素色砼\u201c八\u201d字草坪砖'（智能引号）时
      AI 返回 '素色砼"八"字草坪砖'（直引号）
      merge 找不到 → 整批跳过（静默吞掉）

    边界情况：None / 空字符串直接返回。
    """
    if not s:
        return s
    return (
        s
        .replace('\u201c', '"').replace('\u201d', '"')   # 智能双引号 → 直双引号
        .replace('\u2018', "'").replace('\u2019', "'")   # 智能单引号 → 直单引号
        .replace('\u3001', ',')                            # 中文句号 → 逗号
    )


# ── 2. L3 列表格式化 ───────────────────────────────────────────────
def format_l3_list(taxonomy: List[dict]) -> str:
    """把 64 L3 拼成短文本（每行一条）。

    重要：t['l3'] 字段已是完整编码（如 "01.04.01"），**不要再拼 l1.l2**。
    早期版本输出 "{l1}.{l2}.{l3} {name_l3}/{name_l1}"，AI 看到后
    会拼出 5 段（"01.01.04.01.04.01"），因为把 l1.l2.l3 当独立段。
    """
    lines = []
    for t in taxonomy:
        # 直接用 l3（已是完整 3 段编码），层级通过 name 助理解
        lines.append(f"{t['l3']}  [{t['name_l1']} > {t['name_l2']} > {t['name_l3']}]")
    return "\n".join(lines)


# ── 3. 品种列表格式化 ──────────────────────────────────────────────
def format_breed_list(items: List[dict]) -> str:
    """待校验品种拼成短文本（含 spec / unit / breed / current_l3）。

    兼容两种输入形态：
      A. 校验场景：items = [{breed_clean, current_l3, current_confidence}]
         → 输出：breed=<breed_clean> | current_l3=...
      B. 补全场景：items = [{breed, breed_clean, spec, unit, current_l3}]
         → 输出：breed=<breed> | spec=<spec> | unit=<unit> | current_l3=...
    """
    lines = []
    for i, it in enumerate(items, 1):
        breed = it.get('breed') or it.get('breed_clean', '')
        spec = it.get('spec', '')
        unit = it.get('unit', '')
        cur_l3 = it.get('current_l3', '')
        if spec or unit:
            lines.append(f"  {i}. breed={breed} | spec={spec} | unit={unit} | current_l3={cur_l3}")
        else:
            lines.append(f"  {i}. breed={breed} | current_l3={cur_l3}")
    return "\n".join(lines)


# ── 4. AI 输出合法性校验 ──────────────────────────────────────────
def validate_l3_in_taxonomy(suggested_l3: str, valid_l3_set: set) -> bool:
    """校验 AI 给的 L3 是否在 64 L3 全集里。

    失败场景：AI 编造 L3（如 "99.99.99"）→ 丢弃。
    成功场景：L3 命中 valid_l3_set（含 64 个合法编码）→ 接受。
    """
    if not suggested_l3:
        return False
    return str(suggested_l3).strip() in valid_l3_set


# ── 5. AI 输出合并回 batch ────────────────────────────────────────
def merge_ai_results(
    batch: List[dict],
    ai_results: List[dict],
    valid_l3_set: set,
    *,
    l3_key_in_ai: str = "l3",
    l3_key_in_batch: str = "current_l3",
) -> Tuple[List[dict], int]:
    """合并 AI 输出 + 原始 batch（按 breed_clean 关联，含归一化匹配）。

    返回 (merged_list, skipped_count)：
      - merged_list: 每条包含 AI 输出 + 原始 batch 信息（带 ai_valid 标记）
      - skipped_count: AI 返回但 batch 里找不到的条目数（异常情况）

    核心逻辑：
      1. 用 batch 建 by_bc 索引（精确匹配 + 归一化索引）
      2. 对 AI 返回的每条结果，优先精确匹配，失败时回退归一化匹配
      3. 校验 suggested_l3 合法性（不在 valid_l3_set 则 ai_valid=False）
      4. 跳过 breed_clean 完全找不到的（join 失败时静默丢弃）

    修复触发：scripts/ai_validate_l3_map.py 跑 4073 条时漏 2 条，
    根因就是 AI 把智能引号归一化后 by_bc 找不到。归一化匹配后修复。
    """
    by_bc = {it['breed_clean']: it for it in batch}
    by_bc_norm = {norm_bc(k): v for k, v in by_bc.items()}
    merged = []
    skipped = 0
    for r in ai_results:
        bc = r.get('breed_clean', '')
        orig = by_bc.get(bc) or by_bc_norm.get(norm_bc(bc))
        if not orig:
            skipped += 1
            continue
        sug_l3_raw = r.get(l3_key_in_ai, orig.get(l3_key_in_batch, ''))
        sug_l3 = str(sug_l3_raw).strip() if sug_l3_raw is not None else ''
        is_valid = validate_l3_in_taxonomy(sug_l3, valid_l3_set)
        merged.append({
            **orig,
            'suggested_l3': sug_l3,
            'ai_confidence': float(r.get('confidence', 0) or 0),
            'ai_reason': r.get('reason', ''),
            'ai_valid': is_valid,
            # 完整 v2 字段（service.classify_v2_batch 用）
            'l1': r.get('l1', ''),
            'l2': r.get('l2', ''),
            'l4': r.get('l4', 'UNCLASSIFIED'),
            'name_l1': r.get('name_l1', ''),
            'name_l2': r.get('name_l2', ''),
            'name_l3': r.get('name_l3', ''),
            'gb_50500': r.get('gb_50500', ''),
            'quota_ref': r.get('quota_ref', ''),
            'ifc_class': r.get('ifc_class', ''),
            'uniclass_ss': r.get('uniclass_ss', ''),
            'eng_part': r.get('eng_part', ''),
            'eng_stage': r.get('eng_stage', ''),
            'main_or_aux': r.get('main_or_aux', ''),
            'unit': r.get('unit', ''),
        })
    return merged, skipped
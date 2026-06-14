"""ai_service.py - 统一 AI 服务入口（带缓存）

设计目标：
  1. ETL 与 dashboard 解耦：所有 AI 调用走这里
  2. 缓存层：重复 spec 文本不再重复送 AI（ai_cache.db）
  3. 统一鉴权：读 openclaw.json 拿 token
  4. 统一重试：失败有 fallback
  5. 计量：每次调用都计入 stats

实际调用路径（不绕道 dashboard）：
  ETL → ai_service → OpenClaw gateway (localhost:18789/v1/chat/completions)

兼容旧接口：
  - Prompt 模板从 prompts.yml 加载（路径由 paths.PROMPTS_YML 解析）
  - 修改 prompts.yml 后下次 AI 调用自动重读（mtime 检测）
  - 缺失时回退到 ai.prompts.BUILTIN_FALLBACK
"""

import hashlib
import json
import os
import sys
import time
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from gov_price_etl.ai import cache as ai_cache
from gov_price_etl.ai.prompts import format_prompt, get_prompt
from gov_price_etl.paths import (
    PROJECT_ROOT,
    SPEC_RULES_DB,
)
import requests

# ── 配置 ──────────────────────────────────────────────────────────────
GATEWAY_URL = os.environ.get("OPENCLAW_GATEWAY_URL", "http://localhost:18789")
OPENCLAW_CONFIG = os.path.expanduser("~/.openclaw/openclaw.json")


def _read_token() -> str:
    try:
        with open(OPENCLAW_CONFIG) as f:
            d = json.load(f)
        return d.get("gateway", {}).get("auth", {}).get("token", "")
    except Exception:
        return ""


# 旧 BUILTIN_PROMPTS 字典已迁移到 ai/prompts.py 的 BUILTIN_FALLBACK。
# 旧 _load_prompts() 函数已废弃（ai/prompts.py 的 get_prompts/get_prompt 是替代）。


def _get_ref_attr_names() -> str:
    """从 data/breed_spec_rules.db 读取已有属性名（兼容 dashboard 的 ref_names 逻辑）"""
    db_path = str(SPEC_RULES_DB)
    if not os.path.exists(db_path):
        return "diameter, length, width, height, thickness, grade, material, pressure, voltage, power"
    try:
        import sqlite3
        conn = sqlite3.connect(db_path)
        names = [r[0] for r in conn.execute("SELECT DISTINCT attr FROM breed_spec_rules").fetchall()]
        conn.close()
        return ", ".join(names) if names else "diameter, length, width, height, thickness, grade"
    except Exception:
        return "diameter, length, width, height, thickness, grade"


# ── 计数器（process 内）──────────────────────────────────────────────
_stats = {
    "classify_calls": 0,   # 调 AI 分类次数
    "classify_cached": 0,  # 缓存命中次数
    "parse_calls": 0,
    "parse_cached": 0,
    "parse_failed": 0,
    "classify_failed": 0,
}


def get_stats() -> dict:
    """Return process-level AI call stats + cache stats."""
    return {**_stats, "cache": ai_cache.stats()}


def _reset_stats():
    for k in _stats:
        _stats[k] = 0


def reset_stats() -> None:
    """公开接口：重置过程内 AI 统计。"""
    _reset_stats()


def _call_gateway(prompt: str, system: str, user: str, timeout: int = 120) -> Tuple[bool, str]:
    """Direct call to OpenClaw gateway chat completions API."""
    token = _read_token()
    if not token:
        return False, "无法读取 OpenClaw token"
    body = json.dumps({
        "model": "openclaw",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "user": user,
    }).encode("utf-8")
    try:
        s = requests.Session()
        s.trust_env = False
        r = s.post(
            f"{GATEWAY_URL}/v1/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
        data = r.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        if not content:
            return False, "AI 返回空内容"
        # Strip ```json ``` fences
        if content.startswith("```"):
            parts = content.split("```")
            content = parts[1] if len(parts) > 1 else parts[0]
            if content.startswith("json"):
                content = content[4:]
        return True, content.strip()
    except Exception as e:
        return False, f"网关调用异常: {e}"


# ── 公开 API ───────────────────────────────────────────────────────

def classify_breed_batch(breeds: List[str], city: str = "") -> Dict[str, str]:
    """
    批量品种分类，返回 {breed: category}。

    流程：
      1. 对每个 breed 计算 cache_key, 查询 ai_cache
      2. 全部命中 → 直接返回（无 AI 调用）
      3. 未命中 → 批量送 AI，AI 返回后回写缓存
      4. AI 失败 → 标记为 "其他"（与旧行为兼容）

    参数:
      breeds: 待分类品种列表
      city: 城市 key（仅用于缓存 key，避免跨城市污染）
    """
    if not breeds:
        return {}
    cfg = get_prompt("classify_breed_batch")
    system_msg = cfg.get("system", "")

    # 1. 查缓存
    uncached = []
    cached_map: Dict[str, str] = {}
    for b in breeds:
        v = ai_cache.get("classify", b, city)
        if v and v.get("category"):
            cached_map[b] = v["category"]
            _stats["classify_cached"] += 1
        else:
            uncached.append(b)

    # 2. 送 AI
    if uncached:
        _stats["classify_calls"] += 1
        breeds_str = "\n".join(f"{i+1}. {b}" for i, b in enumerate(uncached))
        try:
            user_prompt = format_prompt(cfg["template"], breeds=breeds_str)
        except (KeyError, ValueError):
            user_prompt = f"待分类：\n{breeds_str}"
        ok, content = _call_gateway(user_prompt, system_msg, "etl-classify-agent", timeout=180)
        ai_results: Dict[str, str] = {}
        if ok:
            try:
                parsed = json.loads(content)
                results_dict = parsed.get("results", {}) if isinstance(parsed, dict) else {}
                for b in uncached:
                    r = results_dict.get(b) or {}
                    cat = r.get("category", "其他")
                    ai_results[b] = cat
                    # 写缓存（包含 confidence/note 以便后续查询）
                    ai_cache.put("classify", {"category": cat, "confidence": r.get("confidence", 0.9), "note": r.get("note", "")}, b, city)
            except Exception as e:
                _stats["classify_failed"] += 1
                for b in uncached:
                    ai_results[b] = "其他"
        else:
            _stats["classify_failed"] += 1
            for b in uncached:
                ai_results[b] = "其他"

        return {**cached_map, **ai_results}

    return cached_map


def parse_spec_batch(items: List[dict], write_rules: bool = False) -> List[dict]:
    """
    批量规格解析，返回 [{spec, ok, suggestions, failed_reason}]。

    流程：
      1. 对每个 (breed, spec, category) 算 cache_key, 查 ai_cache
      2. 全部命中 → 直接返回（无 AI 调用）
      3. 未命中 → 批量送 AI，AI 返回后回写缓存
      4. AI 失败 → 返回 ok=False（让上游决定是否进 DWS）

    参数:
      items: [{spec, breed, category}, ...]
      write_rules: 是否持久化到规则库（Vector store）。当前实现只写缓存；
                  规则库写回由 dashboard 的 /api/stats/spec-quality/batch-spec-parse
                  在 write_rules=True 时负责（保留此语义）。
    """
    if not items:
        return []
    cfg = get_prompt("batch_spec_parse")
    system_msg = cfg.get("system", "")

    # 1. 查缓存
    results: List[dict] = [None] * len(items)  # type: ignore
    uncached_idx: List[int] = []
    uncached_items: List[dict] = []
    for i, item in enumerate(items):
        spec = item.get("spec", "")
        if not spec:
            results[i] = {"spec": spec, "ok": False, "suggestions": [], "failed_reason": "spec 为空"}
            continue
        cached = ai_cache.get("parse", spec, item.get("breed", ""), item.get("category", ""))
        if cached is not None:
            results[i] = {
                "spec": spec,
                "ok": cached.get("ok", False),
                "suggestions": cached.get("suggestions", []),
                "failed_reason": cached.get("failed_reason", ""),
                "_from_cache": True,
            }
            _stats["parse_cached"] += 1
        else:
            uncached_idx.append(i)
            uncached_items.append(item)

    # 2. 送 AI（串行，20/批，遵守道友要求）
    if uncached_items:
        _stats["parse_calls"] += 1
        BATCH = 20
        TIMEOUT = 300
        for batch_start in range(0, len(uncached_items), BATCH):
            batch_items = uncached_items[batch_start:batch_start + BATCH]
            # 渲染 prompt
            lines = [
                f'[{i+1}] 规格: {it.get("spec","")} | 产品: {it.get("breed","")} | 分类: {it.get("category","")}'
                for i, it in enumerate(batch_items)
            ]
            specs_str = "\n".join(lines)
            try:
                user_prompt = format_prompt(
                    cfg["template"],
                    specs_str=specs_str,
                    batch_size=len(batch_items),
                    ref_names=_get_ref_attr_names(),
                )
            except (KeyError, ValueError):
                user_prompt = f"specs:\n{specs_str}\n\nref_names: {_get_ref_attr_names()}"
            ok, content = _call_gateway(user_prompt, system_msg, "etl-parse-agent", timeout=TIMEOUT)
            if not ok:
                _stats["parse_failed"] += len(batch_items)
                for k, item in enumerate(batch_items):
                    target_pos = uncached_idx[batch_start + k]
                    results[target_pos] = {
                        "spec": item.get("spec", ""),
                        "ok": False,
                        "suggestions": [],
                        "failed_reason": content,
                    }
                    # 失败不写缓存（避免污染），下次还会重试
                continue
            # 解析 AI 返回
            try:
                ai_list = json.loads(content)
                if not isinstance(ai_list, list):
                    raise ValueError("AI 返回不是 JSON 数组")
            except Exception as e:
                _stats["parse_failed"] += len(batch_items)
                for k, item in enumerate(batch_items):
                    target_pos = uncached_idx[batch_start + k]
                    results[target_pos] = {
                        "spec": item.get("spec", ""),
                        "ok": False,
                        "suggestions": [],
                        "failed_reason": f"AI 返回格式错误: {e}",
                    }
                continue
            # 写回 results + 写缓存
            for k, item in enumerate(batch_items):
                target_pos = uncached_idx[batch_start + k]
                spec = item.get("spec", "")
                ai_r = ai_list[k] if k < len(ai_list) else {}
                if not isinstance(ai_r, dict):
                    ai_r = {}
                ok_flag = bool(ai_r.get("ok", False))
                suggestions = ai_r.get("suggestions", []) if ok_flag else []
                rec = {
                    "spec": spec,
                    "ok": ok_flag,
                    "suggestions": suggestions,
                    "failed_reason": ai_r.get("failed_reason", ""),
                }
                results[target_pos] = rec
                # 写缓存（无论 ok 与否都写，下次同 spec 直接复用结果，跳过 AI）
                ai_cache.put("parse", {
                    "ok": ok_flag,
                    "suggestions": suggestions,
                    "failed_reason": ai_r.get("failed_reason", ""),
                }, spec, item.get("breed", ""), item.get("category", ""))

    return results  # type: ignore


# ── 自测 ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if cmd == "stats":
        print(json.dumps(get_stats(), ensure_ascii=False, indent=2))
    elif cmd == "classify":
        breeds = sys.argv[2:] or ["HPB300", "碎石10～30mm", "C30商品混凝土", "雪松"]
        r = classify_breed_batch(breeds, "test")
        print(json.dumps(r, ensure_ascii=False, indent=2))
        print("--- stats ---")
        print(json.dumps(get_stats(), ensure_ascii=False, indent=2))
    elif cmd == "parse":
        items = [{"spec": "φ6", "breed": "HPB300", "category": "钢材金属材料"}]
        r = parse_spec_batch(items)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        print("--- stats ---")
        print(json.dumps(get_stats(), ensure_ascii=False, indent=2))
    elif cmd == "reset":
        _reset_stats()
        print("stats reset")

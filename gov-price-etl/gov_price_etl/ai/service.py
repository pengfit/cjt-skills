"""ai_service.py - 统一 AI 服务入口

设计目标：
  1. ETL 与 dashboard 解耦：所有 AI 调用走这里
  2. 本地规则库前置：调 AI 之前先查 breed_*_rules.db，命中直接返回（无 AI 调用）
     - 分类：breed_category_rules.db（精确 → 模糊 / Jaccard）
     - 解析：breed_spec_rules.db（VecStore.search 关键词相似度）
  3. 统一鉴权：读 openclaw.json 拿 token
  4. 统一重试：失败有 fallback
  5. 计量：每次调用都计入 stats
  6. Prompt 模板从 prompts.yml 加载（路径由 paths.PROMPTS_YML 解析），
     改 yml 后下次 AI 调用自动重读（mtime 检测）

实际调用路径（不绕道 dashboard）：
  ETL → ai_service → OpenClaw gateway (localhost:18789/v1/chat/completions)

兼容旧接口：
  - Prompt 模板从 prompts.yml 加载
  - 缺失时回退到 ai.prompts.BUILTIN_FALLBACK
"""

import json
import os
import sys
import time
from typing import Dict, List, Tuple

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
        return "diameter, length, width, height, thickness, grade, material, pressure, voltage, power"


# ── 计数器（process 内）──────────────────────────────────────────────
_stats = {
    "classify_calls": 0,         # 调 AI 分类次数
    "classify_local_hit": 0,     # 本地规则库命中次数
    "classify_failed": 0,
    "classify_rules_written": 0, # AI 响应写入 breed_category_rules.db 条数
    "classify_rules_failed": 0,
    "parse_calls": 0,
    "parse_local_hit": 0,        # 本地规则库命中次数
    "parse_failed": 0,
    "parse_rules_written": 0,    # AI 响应写入 breed_spec_rules.db 条数
    "parse_rules_failed": 0,
}


def get_stats() -> dict:
    """Return process-level AI call stats."""
    return dict(_stats)


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
      1. 对每个 breed 查 breed_category_rules.db（精确 → 模糊）
      2. 命中 → 直接返回（无 AI 调用）
      3. 未命中 → 批量送 AI
      4. AI 失败 → 标记为 "其他"
      5. AI 成功 → 写回 breed_category_rules.db

    参数:
      breeds: 待分类品种列表
      city: 城市 key（仅用于日志/AI 上下文，不影响本地查询）
    """
    if not breeds:
        return {}
    cfg = get_prompt("classify_breed_batch")
    system_msg = cfg.get("system", "")

    # 1. 查本地规则库（阶段 1+2：精确 → 模糊）
    from gov_price_etl.classify.rules._core import classify_breed_local

    local_map: Dict[str, str] = {}
    uncached: List[str] = []
    for b in breeds:
        cat, _src = classify_breed_local(b)
        if cat:
            local_map[b] = cat
            _stats["classify_local_hit"] += 1
        else:
            uncached.append(b)

    # 2. 送 AI（仅未命中的）
    if uncached:
        _stats["classify_calls"] += 1
        breeds_str = "\n".join(f"{i+1}. {b}" for i, b in enumerate(uncached))
        try:
            user_prompt = format_prompt(cfg["template"], breeds=breeds_str)
        except (KeyError, ValueError):
            user_prompt = f"待分类：\n{breeds_str}"
        ok, content = _call_gateway(user_prompt, system_msg, "etl-classify-agent", timeout=180)
        ai_results: Dict[str, str] = {}
        ai_parsed: Dict[str, dict] = {}  # breed → {category, confidence, note}（入规则库用）
        if ok:
            try:
                parsed = json.loads(content)
                results_dict = parsed.get("results", {}) if isinstance(parsed, dict) else {}
                for b in uncached:
                    r = results_dict.get(b) or {}
                    cat = r.get("category", "其他")
                    confidence = float(r.get("confidence", 0.9) or 0.9)
                    note = r.get("note", "") or ""
                    ai_results[b] = cat
                    ai_parsed[b] = {"category": cat, "confidence": confidence, "note": note}
            except Exception:
                _stats["classify_failed"] += 1
                for b in uncached:
                    ai_results[b] = "其他"
        else:
            _stats["classify_failed"] += 1
            for b in uncached:
                ai_results[b] = "其他"

        # 3. AI 响应入规则库（breed_category_rules.db）
        #    仅在分类有效且非兜底时写入，避免 "其他" 污染 DB
        if ai_parsed:
            try:
                from gov_price_etl.classify.rules.jaccard import batch_insert_breed_rules
                pairs = []
                for b, info in ai_parsed.items():
                    cat = info.get("category", "其他")
                    if cat and cat != "其他":
                        pairs.append((
                            b, cat, "ai",
                            info.get("confidence", 0.9),
                            info.get("note", ""),
                        ))
                if pairs:
                    batch_insert_breed_rules(pairs)
                    _stats["classify_rules_written"] = _stats.get("classify_rules_written", 0) + len(pairs)
            except Exception:
                _stats["classify_rules_failed"] = _stats.get("classify_rules_failed", 0) + 1

        return {**local_map, **ai_results}

    return local_map


def parse_spec_batch(items: List[dict], write_rules: bool = False) -> List[dict]:
    """
    批量规格解析，返回 [{spec, ok, suggestions, failed_reason}]。

    流程：
      1. 对每个 item 查 breed_spec_rules.db（VecStore.search 关键词相似度）
      2. 命中 → 直接返回 suggestions（无 AI 调用）
      3. 未命中 → 送 AI
      4. AI 失败 → 返回 ok=False
      5. AI 成功 → 写回 breed_spec_rules.db（write_rules=True 时）

    参数:
      items: [{spec, breed, category}, ...]
      write_rules: 是否持久化到 breed_spec_rules.db。
                  默认 True：让本地规则库持续增长，节省后续 AI 调用。
    """
    if not items:
        return []
    cfg = get_prompt("batch_spec_parse")
    system_msg = cfg.get("system", "")

    # 1. 查本地规则库（VecStore）
    from gov_price_etl.parse_spec.rules.vector_store import get_vec_store
    vs = get_vec_store()

    results: List[dict] = [None] * len(items)  # type: ignore
    uncached_idx: List[int] = []
    uncached_items: List[dict] = []
    for i, item in enumerate(items):
        spec = item.get("spec", "")
        if not spec:
            results[i] = {"spec": spec, "ok": False, "suggestions": [], "failed_reason": "spec 为空"}
            continue
        breed = item.get("breed", "")
        category = item.get("category", "")
        rules = vs.search(spec=spec, category=category, breed=breed, top_k=8)
        if rules:
            # DB 字段是 code，suggestions 规范用 code_block
            suggestions = [
                {
                    "attr": rule["attr"],
                    "pattern": rule["pattern"],
                    "note": rule.get("note", ""),
                    "code_block": rule.get("code", ""),
                }
                for _score, rule in rules
            ]
            results[i] = {
                "spec": spec,
                "ok": True,
                "suggestions": suggestions,
                "failed_reason": "",
                "_from_local": True,
            }
            _stats["parse_local_hit"] += 1
        else:
            uncached_idx.append(i)
            uncached_items.append(item)

    # 2. 送 AI（仅未命中的，串行 20/批，遵守道友要求）
    if uncached_items:
        _stats["parse_calls"] += 1
        BATCH = 20
        TIMEOUT = 300
        for batch_start in range(0, len(uncached_items), BATCH):
            batch_items = uncached_items[batch_start:batch_start + BATCH]
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
                continue
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
            for k, item in enumerate(batch_items):
                target_pos = uncached_idx[batch_start + k]
                spec = item.get("spec", "")
                ai_r = ai_list[k] if k < len(ai_list) else {}
                if not isinstance(ai_r, dict):
                    ai_r = {}
                ok_flag = bool(ai_r.get("ok", False))
                suggestions = ai_r.get("suggestions", []) if ok_flag else []
                results[target_pos] = {
                    "spec": spec,
                    "ok": ok_flag,
                    "suggestions": suggestions,
                    "failed_reason": ai_r.get("failed_reason", ""),
                }

            # AI 响应入规则库（breed_spec_rules.db）
            #    只有 ok=True 且有有效 suggestions 时写入
            if write_rules and ai_list:
                try:
                    written = 0
                    for k, item in enumerate(batch_items):
                        ai_r = ai_list[k] if k < len(ai_list) else {}
                        if not isinstance(ai_r, dict) or not ai_r.get("ok", False):
                            continue
                        breed = item.get("breed", "")
                        category = item.get("category", "")
                        for s in ai_r.get("suggestions", []) or []:
                            pattern = s.get("pattern", "") or ""
                            attr = s.get("attr", "") or ""
                            note = s.get("note", "") or ""
                            code = s.get("code_block", "") or ""
                            if not pattern or not attr:
                                continue
                            try:
                                if vs.insert(pattern, attr, note, code, breed, category, skip_duplicate=True):
                                    written += 1
                            except Exception:
                                pass
                    _stats["parse_rules_written"] = _stats.get("parse_rules_written", 0) + written
                except Exception:
                    _stats["parse_rules_failed"] = _stats.get("parse_rules_failed", 0) + 1

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

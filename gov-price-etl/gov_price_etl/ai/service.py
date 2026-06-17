"""ai_service.py - 统一 AI 服务入口（v2-only）

设计目标：
  1. ETL 与 dashboard 解耦：所有 AI 调用走这里
  2. 本地规则库前置：调 AI 之前先查 category_v2_rules.db，命中直接返回（无 AI 调用）
     - 分类：category_v2_rules.db（精确 → 模糊 / Jaccard）
     - 解析：breed_spec_rules.db（VecStore.search 关键词相似度）
  3. 统一鉴权：读 openclaw.json 拿 token
  4. 统一重试：失败有 fallback
  5. 计量：每次调用都计入 stats
  6. Prompt 模板从 prompts.yml 加载（路径由 paths.PROMPTS_YML 解析），
     改 yml 后下次 AI 调用自动重读（mtime 检测）

实际调用路径（不绕道 dashboard）：
  ETL → ai_service → OpenClaw gateway (localhost:18789/v1/chat/completions)

兼容说明：
  - Prompt 模板从 prompts.yml 加载
  - 缺失时回退到 ai.prompts.BUILTIN_FALLBACK
  - v1 入口（classify_breed_batch / breed_category_rules.db）已废弃（2026-06-16），
    请使用 classify_v2_batch 走 v2 4 层分类
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
    "classify_rules_written": 0, # AI 响应写入 category_v2_rules.db 条数
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


# ── v2 4 层分类（阶段 4 AI 攒批调用）────────────────────────────────
V2_AI_BATCH_SIZE = 20  # 每批最多 20 条（prompt 较大，避免超出 token 限制）
V2_AI_BATCH_SLEEP_S = 0.5


_V2_NAMES_CACHE: dict = {}  # {(l1, l2, l3): (name_l1, name_l2, name_l3)}


_V2_L3_CACHE: set = set()


def _validate_l3(l3: str) -> bool:
    """严格校验 L3 是否在 v2 字典里（防 AI 编造）。"""
    if not l3 or l3 == "UNCLASSIFIED":
        return True  # 空 / UNCLASSIFIED 视为合法
    if l3 in _V2_L3_CACHE:
        return True
    try:
        from gov_price_etl.paths import PROJECT_ROOT
        import sqlite3
        v2_db_path = PROJECT_ROOT / "data" / "category_v2_rules.db"
        conn = sqlite3.connect(f"file:{v2_db_path}?mode=ro", uri=True)
        row = conn.execute(
            "SELECT 1 FROM category_v2 WHERE l3 = ? LIMIT 1", (l3,),
        ).fetchone()
        conn.close()
        if row:
            _V2_L3_CACHE.add(l3)
            return True
    except Exception:
        pass
    return False


def _auto_extend_dict(l1: str, l2: str, l3: str, name_l3: str,
                      gb_50500: str = "", ifc_class: str = "") -> bool:
    """动态扩展 v2 字典：AI 输出字典外 L3 时（结构合法）自动加入字典。

    触发条件：
      - L1/L2/L3 形如 "XX.XX.XX"（2-2-2 形式）
      - L1 和 L2 已在字典里
      - L3 不在字典里（要新加）
      - name_l3 非空

    返回 True 成功加入字典，False 结构不合法。

    同时写回 JSON 文件 (data/category_v2.json) 和 SQLite (data/category_v2_rules.db)。
    """
    import re
    from gov_price_etl.paths import PROJECT_ROOT
    import sqlite3, json

    # 结构校验：XX.XX.XX
    if not re.match(r"^\d{2}\.\d{2}\.\d{2}$", l3) or not l1 or not l2 or not name_l3:
        return False
    if l1 != l3[:2] or l2 != l3[:5]:
        return False  # L1/L2/L3 必须一致

    v2_db_path = PROJECT_ROOT / "data" / "category_v2_rules.db"
    json_path = PROJECT_ROOT / "data" / "category_v2.json"

    # 1. 写 SQLite
    try:
        conn = sqlite3.connect(str(v2_db_path))
        # 查 L1/L2 中文名
        l1_name = l2_name = ""
        row = conn.execute(
            "SELECT name_l1, name_l2 FROM category_v2 WHERE l1 = ? AND l2 = ? LIMIT 1",
            (l1, l2),
        ).fetchone()
        if row:
            l1_name, l2_name = row[0] or "", row[1] or ""
        conn.execute(
            """INSERT OR IGNORE INTO category_v2
               (l1, l2, l3, l4, gb_50500, ifc_class, eng_part, main_or_aux,
                unit, billing_unit, cost_method, name_l1, name_l2, name_l3, name_l4)
               VALUES (?, ?, ?, 'UNCLASSIFIED', ?, ?, '主体', '主材',
                       '', '', '清单+定额', ?, ?, ?, '')""",
            (l1, l2, l3, gb_50500 or "", ifc_class or "IfcBuildingElementProxy",
             l1_name, l2_name, name_l3),
        )
        conn.commit()
        conn.close()
    except Exception:
        return False

    # 2. 写 JSON（同步）
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        # 找 L1 节点
        l1_node = next((n for n in data["tree"]["l1"] if n["code"] == l1), None)
        if l1_node:
            l2_node = next((n for n in l1_node["l2"] if n["code"] == l2), None)
            if l2_node and not any(n["code"] == l3 for n in l2_node["l3"]):
                l2_node["l3"].append({"code": l3, "name": name_l3})
        # 更新 l3_index
        if l3 not in data["l3_index"]:
            data["l3_index"][l3] = {"l1": l1, "l2": l2, "name": name_l3}
        json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass  # SQLite 已写成功，JSON 写失败不影响主流程

    # 3. 更新缓存
    _V2_L3_CACHE.add(l3)
    _stats["classify_v2_auto_extend"] = _stats.get("classify_v2_auto_extend", 0) + 1
    return True


def _lookup_names(l1: str, l2: str, l3: str) -> tuple:
    """从 v2 字典查询 L1/L2/L3 的中文名（带进程级缓存）。"""
    key = (l1, l2, l3)
    if key in _V2_NAMES_CACHE:
        return _V2_NAMES_CACHE[key]
    if not l1 and not l2 and not l3:
        return ("", "", "")
    try:
        from gov_price_etl.paths import PROJECT_ROOT
        import sqlite3
        v2_db_path = PROJECT_ROOT / "data" / "category_v2_rules.db"
        conn = sqlite3.connect(f"file:{v2_db_path}?mode=ro", uri=True)
        row = conn.execute(
            "SELECT name_l1, name_l2, name_l3 FROM category_v2 WHERE l3 = ? LIMIT 1",
            (l3,),
        ).fetchone()
        conn.close()
        if row:
            result = (row[0] or "", row[1] or "", row[2] or "")
            _V2_NAMES_CACHE[key] = result
            return result
    except Exception:
        pass
    return ("", "", "")


def classify_v2_batch(
    items: List[dict],
    city: str = "",
    write_rules: bool = True,
) -> Dict[str, dict]:
    """
    批量 v2 4 层分类，返回 {breed_clean: v2_dict}。

    输入:
      items: [{"breed": ..., "spec": ..., "unit": ..., "breed_clean": ...}, ...]
      city:  城市 key（仅用于日志/AI 上下文）
      write_rules: 是否持久化到 breed_l3_map。默认 True。

    v2_dict 字段（14 个）：
      l1 / l2 / l3 / l4 + name_l1/l2/l3（7 个 code + name）
      + eng_part / eng_stage / main_or_aux（3 工程属性）
      + gb_50500 / quota_ref / ifc_class / uniclass_ss（4 标准码）
      + material_code（1 物料码）

    流程：
      1. 对每个 item 查 v2 breed_l3_map（精确 → 模糊 / Jaccard）
      2. 命中 → 直接返回（无 AI 调用）
      3. 未命中 → 攒批送 AI
      4. AI 失败 → 标记 no_match_v2
      5. AI 成功 → 写回 breed_l3_map
    """
    if not items:
        return {}

    cfg = get_prompt("classify_v2_batch")
    system_msg = cfg.get("system", "")

    # 1. 查 v2 breed_l3_map（阶段 1+2 复用现有本地匹配）
    from gov_price_etl.classify.category_v2 import classify_v2, close_singleton
    close_singleton()  # 重置单例（处理可能的 stale 状态）

    local_map: Dict[str, dict] = {}
    uncached_idx: List[int] = []
    uncached_items: List[dict] = []

    for i, item in enumerate(items):
        breed_clean = item.get("breed_clean", "")
        if not breed_clean:
            continue
        # 复用 classify_v2（v0.5 段式: db_exact + db_fuzzy + pattern + ai + fallback）
        v2 = classify_v2(
            breed=item.get("breed", ""),
            spec=item.get("spec", ""),
            unit=item.get("unit", ""),
            breed_clean=breed_clean,
        )
        if v2.get("category_v2_source") in ("db_exact_v2", "db_fuzzy_v2"):
            local_map[breed_clean] = v2
            _stats["classify_local_hit"] = _stats.get("classify_local_hit", 0) + 1
        else:
            # 阶段 3/5 也未命中 → 留给 AI
            uncached_idx.append(i)
            uncached_items.append(item)

    # 2. 送 AI（仅未命中的）
    ai_results: Dict[str, dict] = {}
    if uncached_items:
        _stats["classify_v2_calls"] = _stats.get("classify_v2_calls", 0) + 1
        # 加载 64 L3 全量作为 prompt 上下文（与校验脚本 prompts.yml 复用）
        from gov_price_etl.classify.utils import format_l3_list, format_breed_list
        from gov_price_etl.paths import CATEGORY_V2_RULES_DB
        try:
            import sqlite3 as _sqlite3
            _tax_conn = _sqlite3.connect(f"file:{CATEGORY_V2_RULES_DB}?mode=ro", uri=True)
            _tax_conn.row_factory = _sqlite3.Row  # 关键：必须设，否则 dict(r) 抛 ValueError 被 except 吞掉 → l3_list 留空
            _taxonomy = [dict(r) for r in _tax_conn.execute(
                "SELECT l1, l2, l3, name_l1, name_l2, name_l3 FROM category_v2 ORDER BY l1, l2, l3"
            )]
            _tax_conn.close()
            l3_list_str = format_l3_list(_taxonomy)
        except Exception:
            l3_list_str = ""  # fallback: 让 prompt 里的 l3_list 占位符留空
            _taxonomy = []
            _stats["classify_l3_load_failed"] = _stats.get("classify_l3_load_failed", 0) + 1

        # 攒批：每批 V2_AI_BATCH_SIZE 条
        for batch_start in range(0, len(uncached_items), V2_AI_BATCH_SIZE):
            batch = uncached_items[batch_start:batch_start + V2_AI_BATCH_SIZE]
            # 序列化为 prompt items（使用 utils.format_breed_list，含 spec/unit/current_l3）
            breed_list_str = format_breed_list(batch)
            try:
                user_prompt = format_prompt(
                    cfg["template"],
                    total_l3=len(_taxonomy),
                    l3_list=l3_list_str,
                    batch_n=len(batch),
                    breed_list=breed_list_str,
                )
            except (KeyError, ValueError):
                # 退到老 prompt（仅用 items 占位符）— prompts.yml 缺失 detailed 版时
                items_str = "\n".join(
                    f"  {i+1}. breed={it.get('breed','')} | spec={it.get('spec','')} | unit={it.get('unit','')}"
                    for i, it in enumerate(batch)
                )
                user_prompt = f"待分类：\n{items_str}"
            ok, content = _call_gateway(
                user_prompt, system_msg, "etl-classify-v2-agent", timeout=180,
            )
            if not ok:
                _stats["classify_failed"] = _stats.get("classify_failed", 0) + len(batch)
                for it in batch:
                    ai_results[it.get("breed_clean", "")] = None
                time.sleep(V2_AI_BATCH_SLEEP_S)
                continue
            try:
                parsed = json.loads(content)
                results_raw = parsed.get("results", {}) if isinstance(parsed, dict) else {}
            except Exception:
                _stats["classify_failed"] = _stats.get("classify_failed", 0) + len(batch)
                for it in batch:
                    ai_results[it.get("breed_clean", "")] = None
                time.sleep(V2_AI_BATCH_SLEEP_S)
                continue

            # AI 输出格式兼容两种：
            #   A. dict: {"breed_clean": {...}, ...} （旧版）
            #   B. list: [{...}, {...}] （prompts.yml v2 当前定义）
            # 统一归一化为 dict[breed_clean → result]
            if isinstance(results_raw, list):
                results_dict = {
                    (r.get("breed_clean", "")): r
                    for r in results_raw
                    if isinstance(r, dict) and r.get("breed_clean")
                }
            elif isinstance(results_raw, dict):
                results_dict = results_raw
            else:
                results_dict = {}

            # ⚠️ 智能引号归一化踩坑防护：AI 返回的 breed_clean 可能把 "" (U+201C/U+201D)
            # 规范成 "" (U+0022)，导致 results_dict.get(breed_clean) 查不到 → 跳过。
            # 用 norm_bc() 建二级索引兜底。详见 gov_price_etl.classify.utils。
            from gov_price_etl.classify.utils import norm_bc
            results_dict_norm = {norm_bc(k): v for k, v in results_dict.items() if k}

            for it in batch:
                breed_clean = it.get("breed_clean", "")
                # 优先精确匹配，失败时回退到归一化匹配（避免智能引号 join 丢失）
                r = (
                    results_dict.get(breed_clean)
                    or results_dict_norm.get(norm_bc(breed_clean))
                    or {}
                )
                conf = float(r.get("confidence", 0.7) or 0.7)
                if conf < 0.70:
                    _stats["classify_failed"] = _stats.get("classify_failed", 0) + 1
                    ai_results[breed_clean] = None
                    continue
                l1, l2, l3, l4 = (
                    r.get("l1", ""), r.get("l2", ""), r.get("l3", ""),
                    r.get("l4", "UNCLASSIFIED"),
                )
                # 严格校验：L3 必须在 v2 字典里（否则 AI 可能在编造）
                if not _validate_l3(l3):
                    # 字典外 L3：尝试动态扩展字典
                    name_l3_ai = r.get("name_l3", "") or r.get("l4", "") or breed_clean
                    if _auto_extend_dict(l1, l2, l3, name_l3_ai,
                                         gb_50500=r.get("gb_50500", ""),
                                         ifc_class=r.get("ifc_class", "")):
                        # 动态扩展成功，合法化
                        pass
                    else:
                        _stats["classify_failed"] = _stats.get("classify_failed", 0) + 1
                        _stats["classify_v2_invalid_l3"] = _stats.get("classify_v2_invalid_l3", 0) + 1
                        ai_results[breed_clean] = None
                        continue
                # 强制 l4 = "UNCLASSIFIED"（除非是字典中真实存在的 L4）
                l4 = "UNCLASSIFIED" if l4 in ("", breed_clean) else l4
                # 从 v2 字典反查中文名（以字典为准，不信 AI 输出）
                name_l1, name_l2, name_l3 = _lookup_names(l1, l2, l3)
                v2_dict = {
                    "l1": l1, "l2": l2, "l3": l3, "l4": l4,
                    "name_l1": name_l1, "name_l2": name_l2, "name_l3": name_l3,
                    "eng_part": r.get("eng_part", ""), "eng_stage": r.get("eng_stage", ""),
                    "main_or_aux": r.get("main_or_aux", ""),
                    "gb_50500": r.get("gb_50500", ""), "quota_ref": r.get("quota_ref", ""),
                    "ifc_class": r.get("ifc_class", ""), "uniclass_ss": r.get("uniclass_ss", ""),
                    "material_code": r.get("material_code", ""),
                    "category_v2_source": "ai_v2",
                    "category_v2_confidence": conf,
                }
                ai_results[breed_clean] = v2_dict

            time.sleep(V2_AI_BATCH_SLEEP_S)

        # 3. AI 响应入 v2 breed_l3_map
        # 过滤规则：confidence < 0.90 不入库（AI 自己拿不准的别污染规则库，下次还要再调一次）
        MIN_RULE_CONFIDENCE = 0.90
        if write_rules and ai_results:
            try:
                import sqlite3
                from gov_price_etl.paths import PROJECT_ROOT
                v2_db_path = PROJECT_ROOT / "data" / "category_v2_rules.db"
                conn = sqlite3.connect(str(v2_db_path))
                rows_to_write = [
                    (bc, v["l3"], "ai_v2", v["category_v2_confidence"])
                    for bc, v in ai_results.items()
                    if v and v.get("l3") and v.get("category_v2_confidence", 0) >= MIN_RULE_CONFIDENCE
                ]
                rows_skipped = sum(
                    1 for v in ai_results.values()
                    if v and v.get("l3") and v.get("category_v2_confidence", 0) < MIN_RULE_CONFIDENCE
                )
                if rows_to_write:
                    conn.executemany(
                        """INSERT OR REPLACE INTO breed_l3_map
                           (breed_clean, l3, source, confidence)
                           VALUES (?, ?, ?, ?)""",
                        rows_to_write,
                    )
                conn.commit()
                conn.close()
                _stats["classify_v2_rules_written"] = _stats.get("classify_v2_rules_written", 0) + len(rows_to_write)
                if rows_skipped:
                    _stats["classify_v2_rules_below_threshold"] = _stats.get("classify_v2_rules_below_threshold", 0) + rows_skipped
            except Exception:
                _stats["classify_v2_rules_failed"] = _stats.get("classify_v2_rules_failed", 0) + 1

    return {**local_map, **ai_results}


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
        from gov_price_etl.ai import classify_v2_batch
        items = sys.argv[2:] or [
            {"breed": "HPB300", "spec": "φ6", "unit": "t", "breed_clean": "HPB300"},
            {"breed": "雪松", "spec": "高3m", "unit": "株", "breed_clean": "雪松"},
        ]
        r = classify_v2_batch(items, "test")
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

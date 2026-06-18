"""ai_service.py - 统一 AI 服务入口（v2-only）

设计目标：
  1. ETL 与 dashboard 解耦：所有 AI 调用走这里
  2. 本地规则库前置：调 AI 之前先查 category_v3_rules.db，命中直接返回（无 AI 调用）
     - 分类：category_v3_rules.db（精确 → 模糊 / Jaccard）
     - 解析：breed_spec_rules.db（VecStore.search 关键词相似度）
  3. **只走 Dify workflow API**（2026-06-18 起：OpenClaw gateway 路径已废）
     - 分类：app-YId5nS63bZnsEbjKA1GiPuep (etl-classify-v2)
     - 解析：app-kgaF6jNrpd4PytjhUk3VTCQ4 (etl-parse-spec)
     - Dify base URL / api_key 走 ~/.openclaw/dify.json 或 env (DIFY_BASE_URL / DIFY_API_KEY_*)
  4. 统一重试：失败有 fallback（Dify client 内部 5xx 重试 + 业务层 fallback dict）
  5. 计量：每次调用都计入 stats
  6. Prompt 模板从 prompts.yml 加载（路径由 paths.PROMPTS_YML 解析），
     改 yml 后下次 AI 调用自动重读（mtime 检测）

实际调用路径：
  ETL → ai.service._ai_invoke → dify_client.DifyClient → Dify /v1/workflows/run

兼容说明：
  - Prompt 模板从 prompts.yml 加载
  - 缺失时回退到 ai.prompts.BUILTIN_FALLBACK
  - v1 入口（classify_breed_batch / breed_category_rules.db）已废弃（2026-06-16），
    请使用 classify_v3_batch 走 v2 4 层分类
  - 原 _call_gateway (OpenClaw chat/completions) 路径已删除（2026-06-18），
    如需临时回退 OpenClaw，可参考 git 历史 `114afc2` 之前的 service.py
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

# 上海/中国时区 helper（db 入库时间统一走这里，避免 SQLite CURRENT_TIMESTAMP 返回 UTC）
try:
    from zoneinfo import ZoneInfo
    _SH_TZ = ZoneInfo("Asia/Shanghai")
except Exception:
    _SH_TZ = None  # fallback: 依赖 datetime.now() 本地时区


def now_cst() -> str:
    """返回 Asia/Shanghai 时区下的当前时间字符串，格式 'YYYY-MM-DD HH:MM:SS'。"""
    from datetime import datetime
    if _SH_TZ is not None:
        return datetime.now(_SH_TZ).strftime("%Y-%m-%d %H:%M:%S")
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _read_token() -> str:
    """已废：OpenClaw 路径删除后该函数不再被使用，保留仅为避免导入报错。"""
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
    "classify_rules_written": 0, # AI 响应写入 category_v3_rules.db 条数
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


def _call_gateway(prompt: str, system: str, user: str, timeout: int = 120,
                  model: str = None) -> Tuple[bool, str]:
    """已废（2026-06-18）：ETL 不再走 OpenClaw gateway chat/completions。

    所有 ETL AI 调用统一走 Dify workflow（_call_dify_workflow）。
    保留函数签名仅为防止外部脚本引用时 ImportError，调用一律返回失败。

    如需临时回退 OpenClaw 路径，可参考 git 历史 commit `114afc2` 之前的实现。
    """
    return False, (
        "_call_gateway 已废 (2026-06-18)：ETL AI 调用统一走 Dify workflow，"
        "请使用 _ai_invoke(...) → _call_dify_workflow(...)"
    )


# ── Dify workflow 后端 ────────────────────────────────────────────────
# Dify workflow API 的输出端已含 ok/results/raw/err_msg（与 Code 节点 outputs 一致），
# 这里是「调用入口」：把 prompt 拆成 Dify 期望的 inputs 格式，拿到 results 后返回 (ok, content_str)。
#
# 重要：Dify Code 节点已做 JSON 提取 + 容错 + 结构化，外层不需要再剥 ```json``` 围栏。
# 跟 _call_gateway 的差异：Dify 返回 results 是 list/dict（结构化），OpenClaw 返回 content 是 str。
# ETL 侧统一当 str 处理（Dify 的 results 用 json.dumps 转字符串，调用方再 json.loads）。
def _call_dify_workflow(app_id: str, inputs: dict, user: str,
                        timeout: int = 90) -> Tuple[bool, str]:
    """调用 Dify workflow（同步 blocking），返回 (ok, content_str)。

    Args:
        app_id:  app-YId5nS63bZnsEbjKA1GiPuep (classify-v2) / app-kgaF6jNrpd4PytjhUk3VTCQ4 (parse-spec)
        inputs:  workflow start 节点的变量 dict（breed_list / batch_n / total_l3 等）
        user:    调用方标识（Dify 用于会话隔离 / 统计）
        timeout: 同步超时秒

    Returns:
        (ok, content)：
          - ok=True, content=str(json.dumps(outputs['results']))  成功（Dify 已经 JSON 提取过）
          - ok=False, content=错误描述
    """
    # 延迟 import 避免 service.py 被 import 时强制 load Dify 配置
    from gov_price_etl.ai.dify_client import (
        KNOWN_APPS, DifyConfigError, DifyAPIError, call_workflow,
    )

    # 把 alias 解析成完整 app id
    full_app_id = app_id
    if not app_id.startswith("app-"):
        info = KNOWN_APPS.get(app_id)
        if info:
            full_app_id = info["app_id"]
        else:
            return False, f"未知 app alias: {app_id!r}（已知: {list(KNOWN_APPS.keys())}）"

    try:
        resp = call_workflow(full_app_id, inputs, user=user, timeout_s=timeout)
    except DifyConfigError as e:
        return False, f"Dify 配置错误: {e}"
    except DifyAPIError as e:
        return False, f"Dify API 错误: {e}"
    except Exception as e:
        return False, f"Dify 调用异常: {e}"

    if not resp.ok:
        # 优先看 Dify 端 err_msg（业务级错误），其次 HTTP/连接错误
        wf_err = resp.outputs.get("err_msg") if isinstance(resp.outputs, dict) else None
        return False, wf_err or resp.error or f"Dify workflow status={resp.workflow_status!r}"

    # 成功：把 results 序列化为字符串（与 _call_gateway 行为一致，下游统一 json.loads）
    results = resp.outputs.get("results")
    if results is None:
        return False, "Dify outputs 缺 results 字段"
    return True, json.dumps(results, ensure_ascii=False)


# ── 统一 AI 调度器（只走 Dify workflow，2026-06-18 起）───────────────
# 调用方：classify_v3_batch / parse_spec_batch。
# 只需传 dify_inputs（对应 Dify workflow start 节点的变量），user 用于会话隔离。
def _ai_invoke(task: str, *, dify_inputs: dict, user: str,
               timeout: int = 90, **_) -> Tuple[bool, str]:
    """统一 AI 调用入口（仅 Dify workflow）。

    Args:
        task: "classify" | "parse"
        dify_inputs: Dify workflow start 节点的变量 dict
        user: 调用方标识（Dify 用于会话隔离 / 统计）
        timeout: 同步超时秒

    Returns:
        (ok, content_str) — ok=True 时 content 是 json.dumps(outputs['results'])
    """
    from gov_price_etl.ai.dify_client import KNOWN_APPS
    alias = f"etl-{task}-v2" if task == "classify" else f"etl-{task}-spec"
    if alias not in KNOWN_APPS:
        return False, f"未知 task: {task!r}（alias 推断失败）"
    return _call_dify_workflow(alias, dify_inputs, user, timeout=timeout)


# ── v2 4 层分类（阶段 4 AI 攒批调用）────────────────────────────────
V2_AI_BATCH_SIZE = 10  # P1-5: 20→10。prompt 64 L3 + 10 breed 约 40K tokens，低于 64K 限；减半避免超限
V2_AI_BATCH_SLEEP_S = 0.5


_V2_NAMES_CACHE: dict = {}  # {(l1, l2, l3): (name_l1, name_l2, name_l3)}


_V2_L3_CACHE: set = set()
_TAXONOMY_CACHE: list = []  # 全量分类法列表（喂给 AI prompt 防编造）


def _validate_l3(l3: str) -> bool:
    """严格校验 L3 是否在 v2 字典里（防 AI 编造）。"""
    if not l3 or l3 == "UNCLASSIFIED":
        return True  # 空 / UNCLASSIFIED 视为合法
    if l3 in _V2_L3_CACHE:
        return True
    try:
        from gov_price_etl.paths import PROJECT_ROOT
        import sqlite3
        v2_db_path = PROJECT_ROOT / "data" / "category_v3_rules.db"
        conn = sqlite3.connect(f"file:{v2_db_path}?mode=ro", uri=True)
        row = conn.execute(
            "SELECT 1 FROM category_v3 WHERE l3 = ? LIMIT 1", (l3,),
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

    同时写回 JSON 文件 (data/category_v3.json) 和 SQLite (data/category_v3_rules.db)。
    """
    import re
    from gov_price_etl.paths import PROJECT_ROOT
    import sqlite3, json

    # 结构校验：XX.XX.XX
    if not re.match(r"^\d{2}\.\d{2}\.\d{2}$", l3) or not l1 or not l2 or not name_l3:
        return False
    if l1 != l3[:2] or l2 != l3[:5]:
        return False  # L1/L2/L3 必须一致

    v2_db_path = PROJECT_ROOT / "data" / "category_v3_rules.db"
    json_path = PROJECT_ROOT / "data" / "category_v3.json"

    # 1. 写 SQLite
    try:
        conn = sqlite3.connect(str(v2_db_path))
        # 查 L1/L2 中文名
        l1_name = l2_name = ""
        row = conn.execute(
            "SELECT name_l1, name_l2 FROM category_v3 WHERE l1 = ? AND l2 = ? LIMIT 1",
            (l1, l2),
        ).fetchone()
        if row:
            l1_name, l2_name = row[0] or "", row[1] or ""
        conn.execute(
            """INSERT OR IGNORE INTO category_v3
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
    _stats["classify_v3_auto_extend"] = _stats.get("classify_v3_auto_extend", 0) + 1
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
        v2_db_path = PROJECT_ROOT / "data" / "category_v3_rules.db"
        conn = sqlite3.connect(f"file:{v2_db_path}?mode=ro", uri=True)
        row = conn.execute(
            "SELECT name_l1, name_l2, name_l3 FROM category_v3 WHERE l3 = ? LIMIT 1",
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


def _load_taxonomy_for_prompt() -> list:
    """加载 v2 字典全量 L1/L2/L3 + name，喂给 AI 当参考表。进程级缓存。"""
    if _TAXONOMY_CACHE:
        return _TAXONOMY_CACHE
    try:
        from gov_price_etl.paths import PROJECT_ROOT
        import sqlite3
        v2_db_path = PROJECT_ROOT / "data" / "category_v3_rules.db"
        conn = sqlite3.connect(f"file:{v2_db_path}?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT DISTINCT l1, l2, l3, name_l1, name_l2, name_l3 "
            "FROM category_v3 ORDER BY l1, l2, l3"
        ).fetchall()
        conn.close()
        _TAXONOMY_CACHE.extend([
            {"l1": r[0], "l2": r[1], "l3": r[2],
             "name_l1": r[3] or "", "name_l2": r[4] or "", "name_l3": r[5] or ""}
            for r in rows
        ])
    except Exception as e:
        print(f"    [warn] _load_taxonomy_for_prompt failed: {e}", file=sys.stderr)
    return _TAXONOMY_CACHE


def classify_v3_batch(
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

    cfg = get_prompt("classify_v2_batch")  # P0-fix: yml key 是 classify_v2_batch（不是 classify_v3_batch）
    system_msg = cfg.get("system", "")

    # 1. 查 v2 breed_l3_map（阶段 1+2 复用现有本地匹配）
    from gov_price_etl.classify.category_v3 import classify_v3, close_singleton
    close_singleton()  # 重置单例（处理可能的 stale 状态）

    local_map: Dict[str, dict] = {}
    uncached_idx: List[int] = []
    uncached_items: List[dict] = []

    for i, item in enumerate(items):
        breed_clean = item.get("breed_clean", "")
        if not breed_clean:
            continue
        # 复用 classify_v3（v0.5 段式: db_exact + db_fuzzy + pattern + ai + fallback）
        v2 = classify_v3(
            breed=item.get("breed", ""),
            spec=item.get("spec", ""),
            unit=item.get("unit", ""),
            breed_clean=breed_clean,
        )
        if v2.get("category_v2_source") in ("db_exact_v3", "db_fuzzy_v3"):
            local_map[breed_clean] = v2
            _stats["classify_local_hit"] = _stats.get("classify_local_hit", 0) + 1
        else:
            # 阶段 3/5 也未命中 → 留给 AI
            uncached_idx.append(i)
            uncached_items.append(item)

    # 2. 送 AI（仅未命中的）
    ai_results: Dict[str, dict] = {}
    if uncached_items:
        _stats["classify_v3_calls"] = _stats.get("classify_v3_calls", 0) + 1
        # 加载 v2 字典全量（L1/L2/L3 + name）→ 喂给 AI，避免乱填编码
        # 之前省略导致 AI 复用已有 L3 编码 + 改 name_l3（保温材料→01.04.01 钢构件）
        # 权衡：~5K tokens（64 L3 × ~80 字），小于 64K context 限
        from gov_price_etl.classify.utils import format_breed_list
        _taxonomy = _load_taxonomy_for_prompt()
        l3_list_str = "\n".join(
            f"  {t['l3']}  {t['name_l1']}/{t['name_l2']}/{t['name_l3']}"
            for t in _taxonomy
        ) if _taxonomy else ""

        # 攒批去重：按 (breed_clean, spec, unit) 三元组只送一次 AI
        # v2 体系下 breed_clean 决定 l3，spec/unit 不影响分类，但为保幂等仍按三元组去重
        # 避免「同一材料多期重复出现」导致 AI 调用量爆炸
        from collections import OrderedDict
        _groups: "OrderedDict[tuple, dict]" = OrderedDict()
        for _it in uncached_items:
            _key = (
                _it.get("breed_clean", ""),
                _it.get("spec", ""),
                _it.get("unit", ""),
            )
            if _key not in _groups:
                _groups[_key] = _it
        deduped_uncached = list(_groups.values())
        if len(uncached_items) != len(deduped_uncached):
            print(f"    [AI] 去重: {len(uncached_items)} → {len(deduped_uncached)} (save {len(uncached_items) - len(deduped_uncached)})")
            _stats["classify_v3_dedup_saved"] = _stats.get("classify_v3_dedup_saved", 0) + (
                len(uncached_items) - len(deduped_uncached)
            )

        # 预打开 db 连接（每批 commit，不需要循环重连）
        # 设计变更（C 选项）：每批 AI 调完即写 db，避免「攒批 + 最后 commit」在 token 超限时
        # 全部白调且 db 0 写入。每批 commit 让增量逐步可见，失败时已有部分保留。
        PROTECTED_SOURCES = ("manual", "v1_translated", "v1_translated_v2")
        _v2_conn = None
        if write_rules:
            try:
                import sqlite3
                from gov_price_etl.paths import PROJECT_ROOT
                _v2_db_path = PROJECT_ROOT / "data" / "category_v3_rules.db"
                _v2_conn = sqlite3.connect(str(_v2_db_path))
            except Exception:
                _stats["classify_v3_db_open_failed"] = _stats.get("classify_v3_db_open_failed", 0) + 1
                _v2_conn = None

        # 设计变更（P0-1）：AI 调前先查 db existing，整批命中 → 直接跳过（不调 AI）
        # 解决"主键全冲突但仍走 AI 浪费调用量"问题
        _already_in_db = set()
        if _v2_conn is not None and deduped_uncached:
            try:
                _bc_to_check = [it.get("breed_clean", "") for it in deduped_uncached]
                _bc_to_check = [b for b in _bc_to_check if b]
                if _bc_to_check:
                    _ph = ",".join("?" * len(_bc_to_check))
                    _rows = _v2_conn.execute(
                        f"SELECT breed_clean FROM breed_l3_map_v3 WHERE breed_clean IN ({_ph})",
                        _bc_to_check,
                    ).fetchall()
                    _already_in_db = {r[0] for r in _rows}
            except Exception:
                pass
        if _already_in_db:
            print(f"    [AI] db 预查命中: {len(_already_in_db)}/{len(deduped_uncached)} 已存在，直接跳过 AI")
            _stats["classify_v3_db_pre_hit"] = _stats.get("classify_v3_db_pre_hit", 0) + len(_already_in_db)
            # 整批命中直接返回（不调 AI）
            if len(_already_in_db) == len(deduped_uncached):
                if _v2_conn is not None:
                    try:
                        _v2_conn.close()
                    except Exception:
                        pass
                return {**local_map}
            # 部分命中：只送未命中的给 AI
            deduped_uncached = [it for it in deduped_uncached
                                if it.get("breed_clean", "") not in _already_in_db]
            print(f"    [AI] 实际送 AI: {len(deduped_uncached)} 条 (db 预查后)")

        # 攒批：每批 V2_AI_BATCH_SIZE 条
        _total_batches = (len(deduped_uncached) + V2_AI_BATCH_SIZE - 1) // V2_AI_BATCH_SIZE
        _t_total = time.time()
        for batch_start in range(0, len(deduped_uncached), V2_AI_BATCH_SIZE):
            batch = deduped_uncached[batch_start:batch_start + V2_AI_BATCH_SIZE]
            _t_batch = time.time()
            _batch_idx = batch_start // V2_AI_BATCH_SIZE + 1
            # 序列化为 prompt items（使用 utils.format_breed_list，含 spec/unit/current_l3）
            breed_list_str = format_breed_list(batch)
            # 统一 AI 调度（仅 Dify workflow）
            ok, content = _ai_invoke(
                "classify",
                dify_inputs={
                    "breed_list": breed_list_str,
                    "batch_n": len(batch),
                    "total_l3": len(_taxonomy),
                    "l3_list":l3_list_str
                },
                user=f"etl-classify-v2-agent-{int(time.time()*1000)}",  # 动态 user 避免会话记忆污染
                timeout=90,  # P0-2: 180s→30s 避免 keep-alive 卡死
            )
            if not ok:
                # P0-2: AI 失败写 fallback dict，进 ai_results，让 commit 块处理（不 continue）
                _stats["classify_failed"] = _stats.get("classify_failed", 0) + len(batch)
                _stats["classify_v3_fallback_written"] = _stats.get("classify_v3_fallback_written", 0) + 0  # 计数下面再增
                for it in batch:
                    ai_results[it.get("breed_clean", "")] = {
                        "l1": "", "l2": "", "l3": "", "l4": "UNCLASSIFIED",
                        "name_l1": "", "name_l2": "", "name_l3": "",
                        "eng_part": "", "eng_stage": "", "main_or_aux": "",
                        "gb_50500": "", "quota_ref": "", "ifc_class": "",
                        "uniclass_ss": "", "material_code": "",
                        "category_v2_source": "ai_fallback_v3",
                        "category_v2_confidence": 0.0,
                    }
                # 不 continue，让下面 commit 块写入
            else:
                try:
                    parsed = json.loads(content)
                    # Dify outputs['results'] 直接是 list（workflow end 节点把 results 数组
                    # 当作 outputs 字段整体暴露），不是 {"results": [...]} 包裹结构。
                    # 兼容两种 schema：
                    #   A. dict: {"results": [...]} → 取 .get("results")
                    #   B. list: [...] → 整体作为 results
                    #   C. 其他: dict 里也兼容 "results" 键
                    if isinstance(parsed, dict):
                        results_raw = parsed.get("results", {})
                    elif isinstance(parsed, list):
                        results_raw = parsed
                    else:
                        results_raw = {}
                except Exception:
                    # JSON 解析失败 → 写 fallback dict
                    _stats["classify_failed"] = _stats.get("classify_failed", 0) + len(batch)
                    for it in batch:
                        ai_results[it.get("breed_clean", "")] = {
                            "l1": "", "l2": "", "l3": "", "l4": "UNCLASSIFIED",
                            "name_l1": "", "name_l2": "", "name_l3": "",
                            "eng_part": "", "eng_stage": "", "main_or_aux": "",
                            "gb_50500": "", "quota_ref": "", "ifc_class": "",
                            "uniclass_ss": "", "material_code": "",
                            "category_v2_source": "ai_fallback_v3",
                            "category_v2_confidence": 0.0,
                        }
                    # 不 continue
            # AI 输出格式兼容两种：
            #   A. dict: {"breed_clean": {...}, ...} （旧版）
            #   B. list: [{...}, {...}] （prompts.yml v2 当前定义）
            # 统一归一化为 dict[breed_clean → result]
            if ok:  # 只有 AI 成功才走这路径；失败已在上面写 fallback dict
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
                            _stats["classify_v3_invalid_l3"] = _stats.get("classify_v3_invalid_l3", 0) + 1
                            ai_results[breed_clean] = None
                            continue
                    # 强制 l4 = "UNCLASSIFIED"（除非是字典中真实存在的 L4）
                    l4 = "UNCLASSIFIED" if l4 in ("", breed_clean) else l4
                    # 从 v2 字典反查中文名（以字典为准，不信 AI 输出）
                    name_l1, name_l2, name_l3 = _lookup_names(l1, l2, l3)
                    # 二次校验：AI 输出的 name_l3 跟字典反查不一致 → 拒绝（AI 复用
                    # 已有 L3 编码 + 改语义，导致“保温材料被分类为钢构件”问题）
                    name_l3_ai = (r.get("name_l3") or "").strip()
                    name_l1_ai = (r.get("name_l1") or "").strip()
                    name_l2_ai = (r.get("name_l2") or "").strip()
                    if l3 and name_l3 and (
                        (name_l3_ai and name_l3_ai != name_l3)
                        or (name_l2_ai and name_l2_ai != name_l2)
                        or (name_l1_ai and name_l1_ai != name_l1)
                    ):
                        _stats["classify_failed"] = _stats.get("classify_failed", 0) + 1
                        _stats["classify_v3_name_mismatch"] = _stats.get("classify_v3_name_mismatch", 0) + 1
                        ai_results[breed_clean] = None
                        continue
                    v2_dict = {
                        "l1": l1, "l2": l2, "l3": l3, "l4": l4,
                        "name_l1": name_l1, "name_l2": name_l2, "name_l3": name_l3,
                        "eng_part": r.get("eng_part", ""), "eng_stage": r.get("eng_stage", ""),
                        "main_or_aux": r.get("main_or_aux", ""),
                        "gb_50500": r.get("gb_50500", ""), "quota_ref": r.get("quota_ref", ""),
                        "ifc_class": r.get("ifc_class", ""), "uniclass_ss": r.get("uniclass_ss", ""),
                        "material_code": r.get("material_code", ""),
                        "category_v2_source": "ai_v3",
                        "category_v2_confidence": conf,
                    }
                    ai_results[breed_clean] = v2_dict
            if write_rules and _v2_conn is not None:
                try:
                    # 仅处理本批涉及的 breed_clean（不用全 ai_results）
                    batch_bc = [it.get("breed_clean", "") for it in batch]
                    # batch_bc_valid：正常 AI 成功（有 l3）或 AI 失败走 fallback 两条都入
                    batch_bc_valid = [bc for bc in batch_bc
                                      if bc and ai_results.get(bc)]
                    if batch_bc_valid:
                        placeholders = ",".join("?" * len(batch_bc_valid))
                        existing = _v2_conn.execute(
                            f"SELECT breed_clean, source FROM breed_l3_map WHERE breed_clean IN ({placeholders})",
                            batch_bc_valid,
                        ).fetchall()
                        protected = {row[0] for row in existing if row[1] in PROTECTED_SOURCES}
                    else:
                        protected = set()

                    # 本批待写：正常用 l3，兑底用 L3='其他' 作为占位
                    rows_to_write = []
                    rows_skipped_empty = 0
                    for bc in batch_bc_valid:
                        if bc in protected:
                            continue
                        v = ai_results[bc]
                        if v.get("category_v2_source") == "ai_fallback_v3":
                            # AI 失败兑底：l3=空，用'其他'占位
                            l3, conf, src = "其他", 0.0, "ai_fallback_v3"
                        elif v.get("l3"):
                            l3, conf, src = v["l3"], v["category_v2_confidence"], "ai_v3"
                        else:
                            rows_skipped_empty += 1
                            continue
                        rows_to_write.append((bc, l3, src, conf))
                    rows_skipped_protected = sum(1 for bc in batch_bc_valid if bc in protected)
                    rows_actually_inserted = 0
                    rows_skipped_existing = 0
                    if rows_to_write:
                        bc_in_batch = [r[0] for r in rows_to_write]
                        placeholders2 = ",".join("?" * len(bc_in_batch))
                        exists_now = {
                            row[0] for row in _v2_conn.execute(
                                f"SELECT breed_clean FROM breed_l3_map WHERE breed_clean IN ({placeholders2})",
                                bc_in_batch,
                            ).fetchall()
                        }
                        rows_actually_inserted = len(bc_in_batch) - len(exists_now)
                        rows_skipped_existing = len(exists_now)
                        _v2_conn.executemany(
                            """INSERT OR IGNORE INTO breed_l3_map
                               (breed_clean, l3, source, confidence, created_at, updated_at)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            [(bc, l3, src, conf, now_cst(), now_cst()) for bc, l3, src, conf in rows_to_write],
                        )
                    _v2_conn.commit()
                    _stats["classify_v3_rules_written"] = _stats.get("classify_v3_rules_written", 0) + rows_actually_inserted
                    if rows_skipped_existing:
                        _stats["classify_v3_rules_skipped_existing"] = _stats.get("classify_v3_rules_skipped_existing", 0) + rows_skipped_existing
                    if rows_skipped_protected:
                        _stats["classify_v3_rules_skipped_protected"] = _stats.get("classify_v3_rules_skipped_protected", 0) + rows_skipped_protected
                    if rows_skipped_empty:
                        _stats["classify_v3_rules_no_l3"] = _stats.get("classify_v3_rules_no_l3", 0) + rows_skipped_empty
                except Exception:
                    _stats["classify_v3_rules_failed"] = _stats.get("classify_v3_rules_failed", 0) + 1

            # P1-3: 每批进度 print
            _elapsed = time.time() - _t_batch
            _total_elapsed = time.time() - _t_total
            print(
                f"    [AI] batch {_batch_idx}/{_total_batches}: "
                f"items={len(batch)}, "
                f"written={_stats.get('classify_v3_rules_written', 0)}, "
                f"existing={_stats.get('classify_v3_rules_skipped_existing', 0)}, "
                f"protected={_stats.get('classify_v3_rules_skipped_protected', 0)}, "
                f"fallback={_stats.get('classify_failed', 0)}, "
                f"{_elapsed:.1f}s (total {_total_elapsed:.0f}s)"
            )
            sys.stdout.flush()

            time.sleep(V2_AI_BATCH_SLEEP_S)

        # 循环结束：关闭 db 连接
        if _v2_conn is not None:
            try:
                _v2_conn.close()
            except Exception:
                pass

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

    # P1-4: parse_spec_batch 防御性去重（与 classify_v3_batch 对齐）
    # 外层 dws_sync.py 已按 (breed, spec) 去重，但函数内部加上保险避免重复 AI 调用
    from collections import OrderedDict
    _spec_groups: "OrderedDict[tuple, int]" = OrderedDict()
    for _i, _it in zip(uncached_idx, uncached_items):
        _key = (_it.get("breed", ""), _it.get("spec", ""), _it.get("category", ""))
        if _key not in _spec_groups:
            _spec_groups[_key] = _i
    if len(uncached_items) != len(_spec_groups):
        _saved = len(uncached_items) - len(_spec_groups)
        _stats["parse_dedup_saved"] = _stats.get("parse_dedup_saved", 0) + _saved
        print(f"    [STG3 AI] 去重: {len(uncached_items)} → {len(_spec_groups)} (save {_saved})")
        uncached_items = [_it for _it in uncached_items
                         if (_it.get("breed",""), _it.get("spec",""), _it.get("category","")) in _spec_groups]
        # 同步：uncached_idx 重新对应
        uncached_idx = [_spec_groups[(_it.get("breed",""), _it.get("spec",""), _it.get("category",""))]
                        for _it in uncached_items]

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
            # 统一 AI 调度（仅 Dify workflow）
            ok, content = _ai_invoke(
                "parse",
                dify_inputs={
                    "specs_str": specs_str,
                    "ref_names": _get_ref_attr_names(),
                    "batch_size": len(batch_items),
                },
                user="etl-parse-agent",
                timeout=TIMEOUT,
            )
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
        from gov_price_etl.ai import classify_v3_batch
        items = sys.argv[2:] or [
            {"breed": "HPB300", "spec": "φ6", "unit": "t", "breed_clean": "HPB300"},
            {"breed": "雪松", "spec": "高3m", "unit": "株", "breed_clean": "雪松"},
        ]
        r = classify_v3_batch(items, "test")
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

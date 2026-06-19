#!/usr/bin/env python3
"""
dify_export.py - 从 prompts.yml 自动生成 Dify 1.14.2 workflow DSL YAML。

生成产物：
  dify/parse-spec.yml        — 建材规格解析（返回 suggestions[]）

2026-06-19：etl-classify-v2 已废弃，不再导出（分类走 DeepSeek 版 etl-classify-deepseek，在 Dify 控制台手动维护）

导入方式：Dify → Studio → Workflow → Import from DSL → 选 .yml

═══════════════════════════════════════════════════════════════
Dify 1.14.2 DSL 关键规范（踩坑总结）
═══════════════════════════════════════════════════════════════

1. **Code 节点 `error` 是保留字** — 变量名不能叫 `error`，否则 Dify
   会把它当内置错误字段，其他变量变匿名（显示成 1, 2, 3, 4 数字）。
   → 用 `error_message` / `err_msg` / `parse_error` 等替代

2. **Code 节点 `outputs` 是 dict 格式**（不是 list）：
   ✅ outputs:
        ok:        {type: boolean, children: null}
        results:   {type: array[object], children: null}
   ❌ outputs:
        - {variable: ok, type: boolean}    # 这种格式 Dify 不认

3. **Prompt 变量语法是 `{{#node_id.var_name#}}`**：
   ✅ {{#start.breed_list#}}
   ❌ {{breed_list}}                       # 不是 jinja 标准

4. **prompt_template 每项必须有 `id` 字段**（UUID 字符串）

5. **version: 0.2.0**（Dify 1.14.2 兼容的最新 DSL schema）

6. **Code 节点 Python 返回 dict 的 key 必须严格匹配 outputs 字典的 key**

7. **End 节点 outputs 是 list**（每项有 variable + value_selector，不需要 type）

参考资料：https://github.com/yoloyolo8/dify-workflow-writer
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PROMPTS_YML = ROOT / "prompts.yml"
OUT_DIR = ROOT / "dify"
OUT_DIR.mkdir(exist_ok=True)

DIFY_VERSION = "0.2.0"  # Dify 1.14.2 兼容

# LLM 模型默认配置（导入后可在 Dify UI 改）
DEFAULT_MODEL = {
    "provider": "langgenius/openai/openai",
    "name": "gpt-4o-mini",
    "mode": "chat",
    "completion_params": {"temperature": 0.1},
}


# ── 工具函数 ────────────────────────────────────────────────────────
def new_id() -> str:
    """生成节点级 ID（Dify 用字符串）。"""
    return uuid.uuid4().hex[:16]


def new_uuid() -> str:
    """生成 prompt item 用的 UUID（标准格式）。"""
    return str(uuid.uuid4())


def base_node(node_id: str, ntype: str, title: str, x: int, y: int, h: int = 89) -> dict:
    """生成节点公共字段。"""
    return {
        "id": node_id,
        "type": "custom",
        "position": {"x": x, "y": y},
        "width": 244,
        "height": h,
        "data": {
            "type": ntype,
            "title": title,
        },
    }


def make_edge(src: str, dst: str) -> dict:
    return {
        "id": new_id(),
        "source": src,
        "target": dst,
        "sourceHandle": "source",
        "targetHandle": "target",
        "type": "custom",
        "data": {"sourceType": "start", "targetType": "end"},
        "zIndex": 0,
    }


def make_start_node(inputs: list[dict]) -> dict:
    """start 节点：声明输入变量。"""
    node = base_node("start", "start", "输入参数", x=30, y=300, h=150)
    node["data"]["variables"] = inputs
    node["data"]["desc"] = "定义工作流输入参数与入参约束（类型、必填、默认值）"
    return node


def make_llm_node(node_id: str, title: str, system: str, user_template: str,
                  var_refs: list[str], output_var: str = "text", desc: str = None) -> dict:
    """LLM 节点：使用 Dify 的 {{#node_id.var_name#}} 变量语法。

    Args:
        var_refs: 引用的 start 节点变量名列表（用于在 node 内 variables 字段声明）
    """
    node = base_node(node_id, "llm", title, x=334, y=300, h=118)
    node["data"]["model"] = DEFAULT_MODEL
    node["data"]["prompt_template"] = [
        {"id": new_uuid(), "role": "system", "text": system.strip()},
        {"id": new_uuid(), "role": "user", "text": user_template.strip()},
    ]
    node["data"]["context"] = {"enabled": False, "variable_selector": []}
    node["data"]["vision"] = {"enabled": False}
    node["data"]["desc"] = desc or f"调用 LLM 执行推理，原始输出写入变量 {output_var!r}"
    # variables 字段：声明本节点引用的上游变量
    node["data"]["variables"] = [
        {"variable": v, "value_selector": ["start", v]} for v in var_refs
    ]
    return node


def make_code_node(node_id: str, title: str, code: str,
                   input_var: str, input_value_selector: list,
                   outputs_dict: dict, desc: str = None) -> dict:
    """代码节点：Python3，输出用 dict 格式（不是 list）。

    Args:
        input_var: 函数参数名
        input_value_selector: 入参来源 [node_id, var_name]
        outputs_dict: dict 格式的输出声明 {var_name: {type, children}}
    """
    node = base_node(node_id, "code", title, x=638, y=300, h=82)
    node["data"]["code_language"] = "python3"
    node["data"]["code"] = code.strip()
    node["data"]["variables"] = [
        {"variable": input_var, "value_selector": input_value_selector}
    ]
    # Dify 1.14.2: outputs 必须是 dict 格式
    node["data"]["outputs"] = outputs_dict
    node["data"]["desc"] = desc or "对 LLM 输出进行 JSON 提取、容错解析与结构化校验"
    return node


def make_end_node(outputs: list[dict], desc: str = None) -> dict:
    """End 节点：outputs 是 list，每项含 variable + value_selector。"""
    node = base_node("end", "end", "工作流输出", x=1050, y=300)
    node["data"]["outputs"] = outputs
    node["data"]["desc"] = desc or "工作流最终输出（API 调用返回结构）"
    return node


# ── 标准化 JSON 提取（Python 代码节点）─────────────────────────────
# 关键：返回 dict 的 key 必须严格匹配 outputs dict 的 key
# 用 err_msg 不用 error（Dify Code 节点保留字）
JSON_PARSE_CODE = r'''
import json
import re


def _extract_json(text: str) -> str:
    """健壮提取 JSON 字符串：处理 ```json``` / 前缀说明 / 尾部注释。"""
    text = (text or "").strip()
    # 抠 ```json ... ``` 块
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
    # 找第一个完整 {...} 或 [...] 块（用 stack 计数）
    starts = [i for i, c in enumerate(text) if c in "[{"]
    for s in starts:
        opener = text[s]
        closer = "}" if opener == "{" else "]"
        depth = 0
        in_str = False
        esc = False
        for i in range(s, len(text)):
            c = text[i]
            if esc:
                esc = False
                continue
            if c == "\\":
                esc = True
                continue
            if c == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if c == opener:
                depth += 1
            elif c == closer:
                depth -= 1
                if depth == 0:
                    return text[s : i + 1]
    return text


def main(llm_output):
    """解析 LLM 输出为结构化 dict。

    返回 4 个字段（与 Code 节点 outputs 字典 key 严格对应）：
      - ok          (bool): 解析是否成功
      - results     (list): 分类/解析结果数组
      - raw         (str):  LLM 原始输出（调试用）
      - err_msg     (str): 错误信息（成功时空字符串）— 不用 error（Dify 保留字）
    """
    out = {"ok": False, "results": [], "raw": llm_output or "", "err_msg": ""}
    raw = _extract_json(llm_output or "")
    if not raw:
        out["err_msg"] = "empty LLM output"
        return out
    try:
        data = json.loads(raw)
    except Exception as e:
        out["err_msg"] = f"json.loads failed: {e}"
        return out
    # 兼容三种顶层结构
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        out["ok"] = True
        out["results"] = data["results"]
        return out
    if isinstance(data, dict) and "suggestions" in data:
        # parse_spec 任务：{suggestions: [...]} 包一层
        out["ok"] = True
        out["results"] = [data]
        return out
    if isinstance(data, list):
        out["ok"] = True
        out["results"] = data
        return out
    out["err_msg"] = f"unexpected top-level type: {type(data).__name__}"
    return out
'''.strip()


# ── Prompt 变量语法转换 ────────────────────────────────────────────
def _to_dify_var(user_template: str, var_names: list[str]) -> str:
    """把 prompt 里的 {var} 替换成 Dify 变量语法 {{#start.var#}}。

    重要：Dify 不用 jinja 模板，所以 prompt 里原存的字面 `{{` `}}`
    （Python format 的双花括号转义遗留）会作为字面文本传给 LLM，
    不会被当变量起始符，不用任何转义。
    """
    out = user_template
    for v in var_names:
        out = out.replace("{" + v + "}", "{{#start." + v + "#}}")
    return out


# ── Workflow: 规格解析 ────────────────────────────────────────────
def build_parse_spec(prompts: dict) -> dict:
    cfg = prompts["batch_spec_parse"]
    system_msg = cfg["system"].strip()
    user_tmpl = _to_dify_var(
        cfg["template"].strip(),
        var_names=["specs_str", "ref_names", "batch_size"],
    )

    start_inputs = [
        {
            "type": "text-input",
            "variable": "specs_str",
            "label": "规格文本列表（待解析项）",
            "required": True,
            "max_length": 50000,
            "options": [],
            "placeholder": "每行格式：[N] 规格: <规格文本> | 产品: <产品提示> | 分类: <分类提示>",
        },
        {
            "type": "text-input",
            "variable": "ref_names",
            "label": "属性命名参考集",
            "required": True,
            "max_length": 5000,
            "options": [],
            "default": "diameter, length, width, height, thickness, grade, material, pressure, voltage, power",
            "placeholder": "逗号分隔的属性名候选（如 diameter, length, thickness）",
        },
        {
            "type": "number",
            "variable": "batch_size",
            "label": "批大小（本次规格条数）",
            "required": True,
            "options": [],
            "default": 20,
        },
    ]

    start = make_start_node(start_inputs)
    llm = make_llm_node(
        node_id="llm_parse",
        title="规格解析推理（LLM）",
        system=system_msg,
        user_template=user_tmpl,
        var_refs=["specs_str", "ref_names", "batch_size"],
        output_var="text",
        desc="依据 prompts.yml/batch_spec_parse 调用 LLM 从规格文本中抽取结构化业务属性与解析规则",
    )
    code = make_code_node(
        node_id="code_parse2",
        title="JSON 提取与结构化",
        code=JSON_PARSE_CODE,
        input_var="llm_output",
        input_value_selector=["llm_parse", "text"],
        outputs_dict={
            "ok": {"type": "boolean", "children": None},
            "results": {"type": "array[object]", "children": None},
            "raw": {"type": "string", "children": None},
            "err_msg": {"type": "string", "children": None},
        },
        desc="从 LLM 输出中健壮提取 JSON（剥离 ``` 围栏、前缀说明、尾部注释），并按 Dify 声明类型反序列化",
    )
    end = make_end_node(
        outputs=[
            {"variable": "ok", "value_selector": ["code_parse2", "ok"]},
            {"variable": "results", "value_selector": ["code_parse2", "results"]},
            {"variable": "raw", "value_selector": ["code_parse2", "raw"]},
            {"variable": "err_msg", "value_selector": ["code_parse2", "err_msg"]},
        ],
        desc="对外暴露的工作流输出：results 为规格解析结果数组，ok/err_msg/raw 用于调用方可观测性",
    )

    graph = {
        "edges": [
            make_edge("start", "llm_parse"),
            make_edge("llm_parse", "code_parse2"),
            make_edge("code_parse2", "end"),
        ],
        "nodes": [start, llm, code, end],
        "viewport": {"x": -200, "y": 100, "zoom": 1},
    }

    return {
        "app": {
            "description": (
                "建材规格解析 ETL 工作流。\n"
                "\n"
                "用途：从建材规格文本（如 2000×1000×10、DN80、C30、Φ25×12m）提取结构化业务属性"
                "（diameter / length / width / thickness / grade / material 等），并生成可执行的 Python 正则解析规则（pattern + code_block）。\n"
                "\n"
                "输入：1~20 条规格文本（按行分隔）\n"
                "输出：results 数组（每条规格一个解析对象，含 attr/note/pattern/code_block）、ok/err_msg/raw 可观测字段\n"
                "优先级：本地 breed_spec_rules.db 精确匹配 > 本地关键词相似度 > LLM 推理\n"
                "\n"
                "适用场景：gov-price-etl 价格入库后的规格归一化与解析规则沉淀。\n"
                "维护：scripts/dify_export.py 从 prompts.yml 自动生成（不要手工改本 DSL）。"
            ),
            "icon": "🔧",
            "icon_background": "#D1E9FF",
            "mode": "workflow",
            "name": "etl-parse-spec",
            "use_icon_as_answer_icon": False,
        },
        "dependencies": [],
        "kind": "app",
        "version": DIFY_VERSION,
        "workflow": {
            "conversation_variables": [],
            "environment_variables": [],
            "features": _default_features(),
            "graph": graph,
        },
    }


def _default_features() -> dict:
    return {
        "file_upload": {"enabled": False},
        "opening_statement": "",
        "retriever_resource": {"enabled": False},
        "sensitive_word_avoidance": {"enabled": False},
        "speech_to_text": {"enabled": False},
        "suggested_questions": [],
        "suggested_questions_after_answer": {"enabled": False},
        "text_to_speech": {"enabled": False},
    }


# ── 主流程 ─────────────────────────────────────────────────────────
def main() -> int:
    if not PROMPTS_YML.exists():
        print(f"❌ {PROMPTS_YML} 不存在", file=sys.stderr)
        return 1
    with open(PROMPTS_YML, "r", encoding="utf-8") as f:
        prompts = yaml.safe_load(f)

    print("─" * 60)
    print(f"📥 读入: {PROMPTS_YML}")
    print(f"📤 输出: {OUT_DIR}/")
    print("─" * 60)

    # Workflow（仅 parse-spec，classify-v2 已废弃不再导出）
    w = build_parse_spec(prompts)
    p = OUT_DIR / "etl-parse-spec.yml"
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(w, f, allow_unicode=True, sort_keys=False, default_flow_style=False, width=4096)
    print(f"  ✅ {p.name}  ({p.stat().st_size} bytes)")

    print("─" * 60)
    print("📋 导入步骤：")
    print("   1. 打开 Dify 控制台 → Studio → Workflow")
    print("   2. 右上角 ··· → Import from DSL → 选 .yml")
    print("   3. 导入后检查 LLM 节点模型（默认 gpt-4o-mini，可在节点里改）")
    print("   4. 发布 → 复制 API key")
    print("─" * 60)

    # sanity check
    for p in (p,):
        with open(p, "r", encoding="utf-8") as f:
            d = yaml.safe_load(f)
        nodes = d["workflow"]["graph"]["nodes"]
        edges = d["workflow"]["graph"]["edges"]
        print(f"  🔍 {p.name}: {len(nodes)} nodes / {len(edges)} edges / version={d['version']}")
        for n in nodes:
            t = n["data"]["type"]
            if t == "code":
                outs = n["data"]["outputs"]
                keys = list(outs.keys()) if isinstance(outs, dict) else [o.get("variable") for o in outs]
                print(f"     [code] outputs keys: {keys}  (dict? {isinstance(outs, dict)})")
            if t == "end":
                outs = n["data"]["outputs"]
                keys = [o.get("variable") for o in outs]
                print(f"     [end]  outputs keys: {keys}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

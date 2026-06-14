"""ai/prompts.py - Prompt 模板加载与安全格式化

职责：
  1. 从 `prompts.yml` 加载 prompt 模板（路径见 `paths.PROMPTS_YML`）
  2. 文件 mtime 检测 → 自动热重载
  3. 安全 format：处理模板中字面量 `{xxx}` 举例文本
     （dashboard 原模板里有大量 "{diameter:20mm, material:Q235}" 之类的示例，
      Python str.format() 会把它们当成占位符报 KeyError）

设计：
  - 进程级缓存：`_PROMPTS_CACHE = (mtime, data)`，每次 `get_prompts()` 检查 mtime
  - `reload_prompts()` 强制重读
  - `format_prompt()` 预转义字面量花括号后再调 str.format
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Tuple

import yaml

from gov_price_etl.paths import PROMPTS_YML


# 进程级缓存：(file_mtime, data)
_PROMPTS_CACHE: Tuple[float, Dict[str, Dict[str, str]]] = (0.0, {})


# ── 加载 ──────────────────────────────────────────────────────────────
def _read_prompts_file(path: str) -> Dict[str, Dict[str, str]]:
    """读 yml 文件，返回 {key: {system, template}} 字典。"""
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        # 标准化：每个 value 必须是 dict 且有 system/template
        result: Dict[str, Dict[str, str]] = {}
        for k, v in data.items():
            if not isinstance(v, dict):
                continue
            sys_msg = v.get("system", "")
            tmpl = v.get("template", "")
            if not tmpl:  # 没 template 的跳过
                continue
            result[str(k)] = {"system": str(sys_msg), "template": str(tmpl)}
        return result
    except Exception as e:
        print(f"  [prompts] 加载失败: {e}")
        return {}


def get_prompts(force_reload: bool = False) -> Dict[str, Dict[str, str]]:
    """返回 prompts 字典。如果文件 mtime 变了自动重读。"""
    global _PROMPTS_CACHE
    path = str(PROMPTS_YML)
    if not os.path.exists(path):
        # 文件不存在 → 用空 dict（不报错，调用方有 fallback）
        return {}

    mtime = os.path.getmtime(path)
    cached_mtime, cached_data = _PROMPTS_CACHE

    if force_reload or mtime != cached_mtime:
        data = _read_prompts_file(path)
        _PROMPTS_CACHE = (mtime, data)
    return _PROMPTS_CACHE[1]


def reload_prompts() -> Dict[str, Dict[str, str]]:
    """强制重读 prompts.yml，返回新内容。"""
    return get_prompts(force_reload=True)


# ── 纯文本内置 fallback（prompts.yml 不存在 / key 缺失时用）───────────
# 简化版 prompt：不含复杂示例，str.format() 安全。
BUILTIN_FALLBACK: Dict[str, Dict[str, str]] = {
    "classify_breed_batch": {
        "system": "你是一名建筑工程材料分类专家。",
        "template": "以下品种列表，请逐个分类（限：钢材金属材料/水泥胶凝材料/砂石骨料/混凝土预制构件/砌体墙体材料/防水密封材料/电气材料/给排水材料/园林绿化/其他）：\n{breeds}\n\n输出 JSON: {{\"ok\": true, \"results\": {{\"品种名\": {{\"category\": \"X\", \"confidence\": 0.9, \"note\": \"\"}}}}}}",
    },
    "batch_spec_parse": {
        "system": "你是一个建材规格解析规则生成专家。",
        "template": "你是一个建材规格解析专家。以下是一批规格文本：\n{specs_str}\n\n属性名参考：{ref_names}\n\n输出 JSON 数组，每个元素包含 spec, ok, suggestions（list of {{attr, pattern, code_block}}）。",
    },
}


def get_prompt(name: str) -> Dict[str, str]:
    """按名字取一个 prompt：先 yml，缺失回退到 BUILTIN_FALLBACK。"""
    data = get_prompts()
    if name in data:
        return data[name]
    return BUILTIN_FALLBACK.get(name, {"system": "", "template": ""})


# ── 安全格式化 ────────────────────────────────────────────────────────
# 哨兵字符：用一个不可能在合法 prompt 模板里出现的 Unicode 私有区字符
_SENTINEL = "\uE000"  # Private Use Area


def format_prompt(template: str, **kwargs: Any) -> str:
    """类似 str.format(**kwargs)，但先转义模板中字面量的花括号。

    例：
        template = "正确示例：{diameter:20mm} 不应被当成占位符"
        kwargs = {"diameter": "20mm"}
        → 先把 {diameter:20mm} 里的字面 { 转义为 {{, }} 同样处理
        → 真正的 {diameter} 占位符保留

    实现：
      1. 把每个 {name} 占位符（name 在 kwargs 里）替换成哨兵
      2. 转义所有剩余的 { → {{, } → }}
      3. 把哨兵还原成 {name}
      4. str.format(**kwargs)
    """
    if not template:
        return ""

    # 第一步：占位符 → 哨兵
    sentinel_map: Dict[str, str] = {}
    work = template
    for i, key in enumerate(kwargs.keys()):
        token = f"{_SENTINEL}{i}{_SENTINEL}"
        # 用 str.replace 处理（不调 format，所以字面 { 安全）
        work = work.replace("{" + str(key) + "}", token)
        sentinel_map[token] = "{" + str(key) + "}"

    # 第二步：转义字面花括号
    work = work.replace("{", "{{").replace("}", "}}")

    # 第三步：哨兵还原（现在 { 和 } 都已被双重化，还原需要把哨兵里的内容变回单层）
    # 哨兵本身就是 Unicode 私有区字符，不含 { }，所以替换是安全的
    for token, original in sentinel_map.items():
        work = work.replace(token, original)

    # 第四步：str.format
    return work.format(**kwargs)


# ── 单元自测 ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    # 测试安全格式化
    tmpl = """正确示例：{diameter:20mm, material:Q235}
错误示例：{diameter:20mm, material:Q235, outer_diameter:20mm}

实际值: spec={spec}, breed={breed}"""
    out = format_prompt(tmpl, spec="φ20", breed="HPB300", diameter="20mm")
    print("=== format_prompt 自测 ===")
    print(out)
    assert "{diameter:20mm" in out, "字面花括号没被转义"
    assert "spec=φ20" in out, "占位符没替换"
    print("✓ 通过")

    print()
    print("=== prompts 加载自测 ===")
    p = reload_prompts()
    print(f"加载了 {len(p)} 个 prompt: {list(p.keys())}")
    for k, v in p.items():
        print(f"  {k}: system={len(v['system'])} chars, template={len(v['template'])} chars")

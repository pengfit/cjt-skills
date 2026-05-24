"""parse_spec/base.py - 通用规格解析基类

架构说明：
  - parse() 先试 rules/ 目录下所有规则文件
  - 本地全部未命中 → 调用 fix-case API（仅首次新 pattern）
  - AI 结果只用于本次解析，不自动写文件
  - 规则文件由 fix-case API confirm 模式写入 rules/ 目录

维护方式：
  - 通过 dashboard UI 的"确认写入规则"按钮写入 rules/*.py
  - 禁止在 base.py 中硬编码规则
"""
import re
import json
import os
import hashlib
import glob
import urllib.request
import urllib.error
import threading

# ─── AI 配置 ───────────────────────────────────────────
FIX_CASE_API = "http://localhost:5200/api/stats/spec-quality/fix-case"
FIX_CASE_TOKEN = ""
try:
    with open("/Users/pengfit/.openclaw/openclaw.json") as f:
        FIX_CASE_TOKEN = json.load(f).get("gateway", {}).get("auth", {}).get("token", "")
except Exception:
    pass

# ─── 本地规则缓存（内存 LRU + rules/ 目录持久化）────────
_rules_lock = threading.Lock()
_rules_cache = {}  # {pattern_md5: {"pattern": str, "attr": str, "re": re.Pattern}}


def _load_local_rules():
    """从 rules/ 目录加载所有 .py 规则文件"""
    rules_dir = os.path.join(os.path.dirname(__file__), "rules")
    rules = []
    pattern_re = re.compile(
        r'# ── 自动生成: (.+?) ──\s*\n'
        r'(.*?)(?=\n# ── 自动生成:|\Z)',
        re.DOTALL
    )
    for py_file in sorted(glob.glob(os.path.join(rules_dir, "*.py"))):
        if py_file.endswith("__init__.py"):
            continue
        with open(py_file) as f:
            content = f.read()
        for m in pattern_re.finditer(content):
            note = m.group(1).strip()
            code = m.group(2).strip()
            pat_m = re.search(r"re\.search\(r['\"]([^'\"]+)['\"]", code)
            attr_m = re.search(r'result\[\s*["\']\s*([^"\'\s]+)\s*["\']\s*\]', code)
            if pat_m and attr_m:
                pattern = pat_m.group(1)
                attr = attr_m.group(1)
                try:
                    compiled = re.compile(pattern)
                    rules.append({"note": note, "pattern": pattern, "attr": attr, "re": compiled, "code": code})
                except re.error:
                    continue
    return rules


def _build_cache():
    """重新构建内存规则缓存"""
    with _rules_lock:
        rules = _load_local_rules()
        _rules_cache.clear()
        for r in rules:
            key = hashlib.md5(r["pattern"].encode()).hexdigest()
            _rules_cache[key] = r


def _get_local_rules():
    """获取本地规则（懒加载，线程安全）"""
    if not _rules_cache:
        _build_cache()
    with _rules_lock:
        return list(_rules_cache.values())


def clean_spec(spec: str) -> str:
    """清洗原始 spec 字符串"""
    if not spec or spec in ("/", ""):
        return ""
    s = str(spec).strip().replace("\u00d7", "*")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _call_fix_case(spec: str, breed: str = "", category: str = "") -> dict:
    """调用 fix-case API 获取规则建议（不写入）"""
    body = json.dumps({
        "city": "xian",
        "spec": spec,
        "breed": breed,
        "category": category,
        "expected": {},
        "confirm": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        FIX_CASE_API,
        data=body,
        headers={
            "Authorization": f"Bearer {FIX_CASE_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read())
    except Exception:
        return {"ok": False}


class BaseParseSpec:
    """
    规格解析基类

    解析流程：仅试 rules/ 目录下已确认规则，零 AI 调用。
    spec 查分属性不允许实时调用 AI，未知 pattern 统一返回空 dict。
    """

    def parse(self, spec: str, breed: str = "", category: str = "") -> dict:
        if not spec or spec == "/":
            return {}
        # 乘号归一化（兼容 × * x）
        spec = spec.replace('\u00d7', '*').replace('\u00D7', '*')

        # ── 先试本地已确认规则 ───────────────────────
        for r in _get_local_rules():
            try:
                m = r["re"].search(spec)
                if m:
                    groups = m.groups()
                    result = {}

                    if len(groups) == 1:
                        result[r["attr"]] = groups[0]
                    elif len(groups) > 1:
                        for idx, g in enumerate(groups):
                            result[f"{r['attr']}_{idx}"] = g
                    else:
                        result[r["attr"]] = m.group(0)

                    if r.get("code"):
                        exec_result = {}
                        exec_globals = {"re": re, "result": exec_result, "s": spec}
                        try:
                            exec(r["code"], exec_globals)
                        except Exception:
                            pass
                        for k in list(result.keys()):
                            if k.startswith(r["attr"] + "_"):
                                del result[k]
                        result.update(exec_result)

                    return result
            except re.error:
                continue

        # ── 本地无匹配，调 AI ───────────────────────
        ai_result = _call_fix_case(spec, breed, category)
        if ai_result.get("ok"):
            return ai_result.get("parse_result", {})
        return {}


def parse_with_fix_case(spec: str, confirm: bool = False) -> dict:
    """
    便捷入口：直接调 fix-case
    confirm=True 时写入 rules/ 目录（由 dashboard UI 调用）
    """
    body = json.dumps({
        "city": "xian",
        "spec": spec,
        "expected": {},
        "confirm": confirm,
    }).encode("utf-8")
    req = urllib.request.Request(
        FIX_CASE_API,
        data=body,
        headers={
            "Authorization": f"Bearer {FIX_CASE_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception:
        return {"ok": False, "message": "API 调用失败"}


# 启动时构建缓存
_build_cache()
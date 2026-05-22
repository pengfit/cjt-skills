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
            attr_m = re.search(r"result\['([^']+)'\]\s*=", code)
            if pat_m and attr_m:
                pattern = pat_m.group(1)
                attr = attr_m.group(1)
                try:
                    compiled = re.compile(pattern)
                    rules.append({"note": note, "pattern": pattern, "attr": attr, "re": compiled})
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


def _call_fix_case(spec: str) -> dict:
    """调用 fix-case API 获取规则建议（不写入）"""
    body = json.dumps({
        "city": "xian",
        "spec": spec,
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

    解析流程：
      1. 先试 rules/ 目录下所有规则（零 AI 调用）
      2. 本地全部未命中 → 调用 fix-case AI
      3. AI 结果只用于本次解析，不自动写文件
    """

    def parse(self, spec: str) -> dict:
        spec = clean_spec(spec)
        if not spec:
            return {}

        result = {}

        # ── 1. 试本地已确认规则 ────────────────────────
        for r in _get_local_rules():
            try:
                m = r["re"].search(spec)
                if m:
                    groups = m.groups()
                    if len(groups) == 1:
                        result[r["attr"]] = groups[0]
                    else:
                        for idx, g in enumerate(groups):
                            result[f"{r['attr']}_{idx}"] = g
                    return result
            except re.error:
                continue

        # ── 2. 本地无匹配，调 AI ────────────────────────
        ai_result = _call_fix_case(spec)
        if not ai_result.get("ok"):
            return {}

        for s in ai_result.get("suggestions", []):
            pattern = s.get("pattern", "")
            attr = s.get("attr", "")
            if not pattern or not attr:
                continue
            try:
                m = re.search(pattern, spec)
                if m:
                    groups = m.groups()
                    if len(groups) == 1:
                        result[attr] = groups[0]
                    else:
                        for idx, g in enumerate(groups):
                            result[f"{attr}_{idx}"] = g
                    return result
            except re.error:
                continue

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
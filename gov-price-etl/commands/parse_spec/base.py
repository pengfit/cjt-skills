"""parse_spec/base.py - 通用规格解析基类

新架构：本地只保留最简单的 spec 清洗和兜底逻辑，
真正的解析规则统一通过 fix-case API 动态获取。
"""
import re
import json
import urllib.request
import urllib.error


def clean_spec(spec: str) -> str:
    """清洗原始 spec 字符串"""
    if not spec or spec in ("/", ""):
        return ""
    s = str(spec).strip().replace("\u00d7", "*")
    s = re.sub(r"\s+", " ", s).strip()
    return s


# fix-case API 地址（ETL 和 dashboard 同一台机器）
FIX_CASE_API = "http://localhost:5200/api/stats/spec-quality/fix-case"
FIX_CASE_TOKEN = ""

try:
    with open("/Users/pengfit/.openclaw/openclaw.json") as f:
        FIX_CASE_TOKEN = json.load(f).get("gateway", {}).get("auth", {}).get("token", "")
except Exception:
    pass


def _call_fix_case(spec: str, confirm: bool = False) -> dict:
    """调用 fix-case API，返回 suggestions 或写入结果"""
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
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception:
        return {"ok": False}


class BaseParseSpec:
    """规格解析基类，核心解析规则统一由 fix-case API 维护"""

    def parse(self, spec: str) -> dict:
        spec = clean_spec(spec)
        if not spec:
            return {}

        # 1. 调用 fix-case API 获取规则建议（不写入）
        ai_result = _call_fix_case(spec, confirm=False)
        if not ai_result.get("ok"):
            return {}

        suggestions = ai_result.get("suggestions", [])
        if not suggestions:
            return {}

        # 2. 用 AI 生成的规则逐一提取属性
        result = {}
        for s in suggestions:
            pattern = s.get("pattern", "")
            attr = s.get("attr", "")
            code_block = s.get("code_block", "")
            if not pattern or not attr:
                continue

            try:
                m = re.search(pattern, spec)
                if m:
                    # 提取所有捕获组
                    groups = m.groups()
                    if len(groups) == 1:
                        result[attr] = groups[0]
                    elif len(groups) > 1:
                        # 多个捕获组：按顺序拼成列表或分别设属性
                        for idx, g in enumerate(groups):
                            result[f"{attr}_{idx}"] = g
            except re.error:
                # 正则语法错误，跳过
                continue

        return result


def parse_with_fix_case(spec: str, confirm: bool = False) -> dict:
    """便捷入口：直接调用 fix-case 进行解析/写入"""
    return _call_fix_case(spec, confirm=confirm)
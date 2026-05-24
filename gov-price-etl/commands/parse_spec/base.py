"""
parse_spec/base.py - 通用规格解析基类

架构说明：
  - parse() 先试 rules/ 目录下所有规则文件
  - 本地全部未命中 → 调用 fix-case API（仅首次新 pattern）
  - AI 结果只用于本次解析，不自动写文件
  - 规则文件由 fix-case API confirm 模式写入 rules/ 目录

属性分组 + 互斥退出规则：
  - 每条规则声明自己管辖的 attr 列表（rule["attrs"]）
  - 规则按 priority 从高到低排序，同 attr 规则排在一起
  - parse() 按顺序遍历所有规则，同一 attr 只取第一个匹配成功的结果
  - 匹配成功后立即退出（互斥退出），不继续匹配其他规则
  - 禁止在 exec 代码块里修改他人 attr
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
_rules_cache = {}  # {pattern_md5: rule_dict}


def _load_local_rules():
    """从 rules/ 目录加载所有 .py 规则文件"""
    rules_dir = os.path.join(os.path.dirname(__file__), "rules")
    rules = []
    # 解析规则块：提取 pattern、attrs、priority、exec_code
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

            # 提取正则 pattern
            pat_m = re.search(r"re\.search\(r['\"]([^'\"]+)['\"]", code)
            if not pat_m:
                continue
            pattern = pat_m.group(1)

            # 提取主 attr（第一个写入 result 的 key）
            attr_m = re.search(r'result\[\s*["\']\s*([^"\'\s]+)\s*["\']\s*\]', code)
            if not attr_m:
                continue
            primary_attr = attr_m.group(1)

            # 提取 priority（可选，默认 0）
            pri_m = re.search(r"#\s*priority\s*[:=]\s*(\d+)", code)

            # 提取该规则涉及的所有 attrs（去重，含主 attr）
            all_attrs = set()
            for am in re.finditer(r'result\[\s*["\']\s*([^"\'\s]+)\s*["\']\s*\]', code):
                all_attrs.add(am.group(1))

            try:
                compiled = re.compile(pattern)
                rules.append({
                    "note": note,
                    "pattern": pattern,
                    "primary_attr": primary_attr,
                    "attrs": frozenset(all_attrs),   # 该规则涉及的所有 attr（集合）
                    "priority": int(pri_m.group(1)) if pri_m else 0,
                    "re": compiled,
                    "code": code,
                })
            except re.error:
                continue

    # 按 priority 降序（高优先级先匹配），同 priority 按文件内顺序
    rules.sort(key=lambda r: -r["priority"])
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


def _call_fix_case(spec: str, breed: str = "", category: str = "", confirm: bool = True) -> dict:
    """调用 fix-case API 生成并写入规则（confirm=True 写入本地 rules/）"""
    body = json.dumps({
        "city": "xian",
        "spec": spec,
        "breed": breed,
        "category": category,
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
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return {"ok": False}


class BaseParseSpec:
    """
    规格解析基类

    解析流程：仅试 rules/ 目录下已确认规则，零 AI 调用。
    spec 查分属性不允许实时调用 AI，未知 pattern 统一返回空 dict。

    属性分组 + 互斥退出：
      - 已设置的 attr 不允许被后续规则覆盖
      - 每条规则只管自己声明的 attrs
      - 同 attr 只取第一个匹配成功的结果（高 priority 优先）
    """

    def parse(self, spec: str, breed: str = "", category: str = "") -> dict:
        if not spec or spec == "/":
            return {}

        rules = _get_local_rules()
        if not rules:
            return {}

        # 已成功提取的 attr 集合（互斥退出核心）
        resolved_attrs = {}
        # 已访问过的 attr（防止同 attr 多规则竞争）
        claimed_attrs = set()

        for r in rules:
            # 跳过该规则已声明但已被占用的 attr
            if r["attrs"] & claimed_attrs:
                continue

            try:
                m = r["re"].search(spec)
                if not m:
                    continue
            except re.error:
                continue

            groups = m.groups()
            exec_result = {}

            # ── 执行规则代码块（只写自己的 attrs）────────
            if r.get("code"):
                safe_globals = {"re": re, "result": exec_result, "s": spec}
                try:
                    exec(r["code"], safe_globals)
                except Exception:
                    pass

            # ── 合并结果（只写入未被他者占领的 attr）──
            for attr, value in exec_result.items():
                if value and attr not in claimed_attrs:
                    resolved_attrs[attr] = value
                    claimed_attrs.add(attr)

            # ── 框架默认提取（捕获纯 groups 情况）────
            if not exec_result:
                if len(groups) == 1:
                    attr = r["primary_attr"]
                    if attr not in claimed_attrs:
                        resolved_attrs[attr] = groups[0]
                        claimed_attrs.add(attr)
                elif len(groups) > 1:
                    for idx, g in enumerate(groups):
                        attr = f"{r['primary_attr']}_{idx}"
                        if g and attr not in claimed_attrs:
                            resolved_attrs[attr] = g
                            claimed_attrs.add(attr)
                else:
                    attr = r["primary_attr"]
                    if attr not in claimed_attrs:
                        resolved_attrs[attr] = m.group(0)
                        claimed_attrs.add(attr)

            # ── 互斥退出：该规则的所有 attrs 均已处理完，直接返回
            # 只要任一 attr 被写入，即认为该规则成功，直接返回（不匹配后续规则）
            return resolved_attrs

        return {k: v for k, v in resolved_attrs.items() if v}

# 启动时构建缓存
_build_cache()
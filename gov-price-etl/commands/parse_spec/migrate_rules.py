#!/usr/bin/env python3
"""Migration: write _infer_rule_suggestion built-in rules to rules/*.py files"""
import re, os

RULES_DIR = "/Users/pengfit/.openclaw/workspace/skills/gov-price-etl/commands/parse_spec/rules"
os.makedirs(RULES_DIR, exist_ok=True)

# Built-in rules from _infer_rule_suggestion (provenance.py)
BUILTIN_RULES = [
    {
        "attr": "diameter",
        "note": "钢管 D*N*N: D*N*N",
        "pattern": r"^D(\d+)\*(\d+)$",
        "lines": [
            "m = re.search(r'^D(\\d+)\\*(\\d+)$', s)",
            "if m:",
            "    result['diameter'] = 'D' + m.group(1)",
            "    result['thickness'] = m.group(2) + 'mm'",
        ],
    },
    {
        "attr": "diameter",
        "note": "JDG管: JDGΦ",
        "pattern": r"JDGΦ(\d+)\*(\d+(?:\.\d+)?)\s*mm",
        "lines": [
            "m = re.search(r'JDGΦ(\\d+)\\*(\\d+(?:\\.\\d+)?)\\s*mm', s)",
            "if m:",
            "    result['diameter'] = 'Φ' + m.group(1)",
            "    result['thickness'] = m.group(2) + 'mm'",
        ],
    },
    {
        "attr": "diameter",
        "note": "Φ管径+壁厚: ΦN*Nmm",
        "pattern": r"Φ(\d+)\*(\d+(?:\.\d+)?)\s*mm",
        "lines": [
            "m = re.search(r'Φ(\\d+)\\*(\\d+(?:\\.\\d+)?)\\s*mm', s)",
            "if m:",
            "    result['diameter'] = 'Φ' + m.group(1)",
            "    result['thickness'] = m.group(2) + 'mm'",
        ],
    },
    {
        "attr": "grade",
        "note": "水泥等级: 袋装P.S.A",
        "pattern": r"袋装\s*P\.S\.A\s*(\d+\.?\d*)",
        "lines": [
            "m = re.search(r'袋装\\s*P\\.S\\.A\\s*(\\d+\\.?\\d*)', s)",
            "if m:",
            "    result['grade'] = 'P.S.A' + m.group(1)",
        ],
    },
    {
        "attr": "width",
        "note": "瓷砖W*H*T: W*H*Tmm",
        "pattern": r"(?:普通\s*)?(\d+)\s*\*\s*(\d+)\s*\*\s*(\d+)\s*mm$",
        "lines": [
            "m = re.search(r'(?:普通\\s*)?(\\d+)\\s*\\*\\s*(\\d+)\\s*\\*\\s*(\\d+)\\s*mm$', s)",
            "if m:",
            "    result['width'] = m.group(1) + 'mm'",
            "    result['height'] = m.group(2) + 'mm'",
            "    result['thickness'] = m.group(3) + 'mm'",
        ],
    },
    {
        "attr": "width",
        "note": "瓷砖W*H: W*Hmm",
        "pattern": r"(?:普通\s*)?(\d+)\s*\*\s*(\d+)\s*mm$",
        "lines": [
            "m = re.search(r'(?:普通\\s*)?(\\d+)\\s*\\*\\s*(\\d+)\\s*mm$', s)",
            "if m:",
            "    result['width'] = m.group(1) + 'mm'",
            "    result['height'] = m.group(2) + 'mm'",
        ],
    },
    {
        "attr": "width",
        "note": "金属材料: W*H重型",
        "pattern": r"(\d+)\s*\*\s*(\d+)\s*重型",
        "lines": [
            "m = re.search(r'(\\d+)\\s*\\*\\s*(\\d+)\\s*重型', s)",
            "if m:",
            "    result['width'] = m.group(1) + 'mm'",
            "    result['height'] = m.group(2) + 'mm'",
        ],
    },
    {
        "attr": "width",
        "note": "尺寸A*B*C(L): A*B*C(L)",
        "pattern": r"(\d+)\s*\*\s*(\d+)\s*\*\s*(\d+)\s*\([Lℓ]\)",
        "lines": [
            "m = re.search(r'(\\d+)\\s*\\*\\s*(\\d+)\\s*\\*\\s*(\\d+)\\s*\\([Lℓ]\\)', s)",
            "if m:",
            "    result['width'] = m.group(1) + 'mm'",
            "    result['height'] = m.group(2) + 'mm'",
            "    result['thickness'] = m.group(3) + 'mm'",
        ],
    },
    {
        "attr": "grade",
        "note": "保温等级+干密度: B*级干密度",
        "pattern": r"(B\d)级.*?干密度(\d+)\s*kg/m3",
        "lines": [
            "m = re.search(r'(B\\d)级.*?干密度(\\d+)\\s*kg/m3', s)",
            "if m:",
            "    result['grade'] = m.group(1) + '级'",
            "    result['material'] = '干密度' + m.group(2) + 'kg/m3'",
        ],
    },
    {
        "attr": "thickness",
        "note": "板厚: 板叠厚Xmm",
        "pattern": r"板[叠厚]?(\d+(?:\.\d+)?)\s*mm",
        "lines": [
            "m = re.search(r'板[叠厚]?(\\d+(?:\\.\\d+)?)\\s*mm', s)",
            "if m:",
            "    result['thickness'] = m.group(1) + 'mm'",
        ],
    },
    {
        "attr": "cores",
        "note": "光纤芯数: N芯",
        "pattern": r"(\d+)芯",
        "lines": [
            "m = re.search(r'(\\d+)芯', s)",
            "if m:",
            "    result['cores'] = m.group(1) + '芯'",
        ],
    },
    {
        "attr": "material",
        "note": "钢材SF型号: SFN",
        "pattern": r"^(SF\d+)",
        "lines": [
            "m = re.search(r'^(SF\\d+)', s)",
            "if m:",
            "    result['material'] = m.group(1)",
        ],
    },
]

# Group rules by attr
by_attr = {}
for r in BUILTIN_RULES:
    by_attr.setdefault(r["attr"], []).append(r)

# Write each attr's rules to a single file
for attr, rules in by_attr.items():
    fpath = os.path.join(RULES_DIR, f"{attr}.py")
    with open(fpath, "w") as f:
        f.write(f"# {attr} 规则文件 - 由 migrate_rules.py 生成\n\n")
        for r in rules:
            f.write(f"# ── 自动生成: {r['note']} ──\n")
            for ln in r["lines"]:
                f.write(ln + "\n")
            f.write("\n")
    # Verify compile
    code = open(fpath).read()
    try:
        compile(code, fpath, "exec")
        print(f"OK: {attr}.py ({len(rules)} rules)")
    except SyntaxError as e:
        print(f"FAIL: {attr}.py - {e}")

# Clear existing rule cache so next parse reloads
import sys
sys.path.insert(0, "/Users/pengfit/.openclaw/workspace/skills/gov-price-etl/commands")
from parse_spec import base
base._rules_cache.clear()
print("Cache cleared, next parse() will rebuild from rules/")
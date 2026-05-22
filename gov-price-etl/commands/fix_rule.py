"""
fix_rule.py - 从 spec 错误样本自动分析并写入 base.py 规则

使用方式：
    python3 fix_rule.py --spec "D720*8" --expected '{"diameter":"D720","thickness":"8mm"}'
    python3 fix_rule.py --spec "袋装P.S.A32.5" --expected '{"grade":"P.S.A32.5"}'

流程：
    1. patterns_for() 根据 spec+expected 生成候选规则（含原生代码行）
    2. 找 base.py 同类规则 marker 位置（用 get_insert_after_line）
    3. 插入备份 → 验证测试集 → 通过则保留，否则 rollback
"""
import re
import sys
import os
import json
import shutil
import argparse
import subprocess
from pathlib import Path

BASE_PY = Path(__file__).parent / "parse_spec" / "base.py"
VALIDATE = Path(__file__).parent / "spec_validate.py"


def run_validate():
    """返回 (passed, total)"""
    r = subprocess.run(
        [sys.executable, str(VALIDATE)],
        capture_output=True, text=True
    )
    out = r.stdout + r.stderr
    for line in out.splitlines():
        m = re.search(r"(\d+)/(\d+)\s*[通过passesx]", line)
        if m:
            return int(m.group(1)), int(m.group(2))
    return 0, 0


def get_insert_after_line(content: str, attr: str) -> int:
    """同类 attr 规则最后 marker 行的 0-indexed 位置"""
    markers = {
        "diameter": ["# 4. 管径:", "# 4e. Φ", "# 4f. 纯 Φ"],
        "thickness": ["# 1. 厚度"],
        "width": ["# 3. 3D"],
        "height": ["# 3. 3D"],
        "grade": ["# 7. 材质"],
        "material": ["# 7. 材质"],
        "cores": ["# 2. 电缆"],
        "cross_section": ["# 2. 电缆"],
        "ring_stiffness": ["# 5. 环刚度"],
        "pressure": ["# 6. 压力"],
    }.get(attr, [f"# {attr}"])

    positions = []
    for i, line in enumerate(content.splitlines()):
        for mk in markers:
            if mk in line:
                positions.append(i)
    return max(positions) if positions else 10


def patterns_for(spec: str, expected: dict) -> list:
    """
    生成候选规则列表，每条 rule 包含：
        attr       - 属性名
        note      - 描述
        code_lines - base.py 代码行（list[str]，不含缩进前缀）
    """
    s = spec.strip()
    rules = []
    diam = expected.get("diameter", "")
    thick = expected.get("thickness", "")
    wid = expected.get("width", "")
    hght = expected.get("height", "")
    grd = expected.get("grade", "")
    mat = expected.get("material", "")

    # 1. 钢管 D*N*N（缺长度：只有直径+壁厚）
    if diam.startswith("D") and thick.endswith("mm"):
        rules.append({
            "attr": "diameter",
            "note": f"钢管 D*N*N: {spec}→{expected}",
            "code_lines": [
                "m = re.search(r'^D(\\d+)\\*(\\d+)$', s)",
                "if m:",
                "    result['diameter'] = 'D' + m.group(1)",
                "    result['thickness'] = m.group(2) + 'mm'",
            ],
        })

    # 2. JDGΦ管径*壁厚
    if "JDGΦ" in s and thick.endswith("mm"):
        rules.append({
            "attr": "diameter",
            "note": f"JDG管: {spec}",
            "code_lines": [
                "m = re.search(r'JDGΦ(\\d+)\\*(\\d+(?:\\.\\d+)?)\\s*mm', s)",
                "if m:",
                "    result['diameter'] = 'Φ' + m.group(1)",
                "    result['thickness'] = m.group(2) + 'mm'",
            ],
        })

    # 3. 通用Φ管径*壁厚
    if "Φ" in s and thick.endswith("mm") and "JDG" not in s:
        rules.append({
            "attr": "diameter",
            "note": f"Φ管径+壁厚: {spec}",
            "code_lines": [
                "m = re.search(r'Φ(\\d+)\\*(\\d+(?:\\.\\d+)?)\\s*mm', s)",
                "if m:",
                "    result['diameter'] = 'Φ' + m.group(1)",
                "    result['thickness'] = m.group(2) + 'mm'",
            ],
        })

    # 4. 水泥等级 袋装P.S.A32.5
    if "袋装" in s and "P.S.A" in s:
        rules.append({
            "attr": "grade",
            "note": f"水泥等级: {spec}",
            "code_lines": [
                "m = re.search(r'袋装\\s*P\\.S\\.A\\s*(\\d+\\.?\\d*)', s)",
                "if m:",
                "    result['grade'] = 'P.S.A' + m.group(1)",
            ],
        })

    # 5. 瓷砖普通W*Hmm（不带厚度）
    m2d = re.match(r"(?:普通\s*)?(\d+)\s*\*\s*(\d+)\s*mm", s)
    if m2d and wid and not thick:
        rules.append({
            "attr": "width",
            "note": f"瓷砖W*H: {spec}",
            "code_lines": [
                "m = re.search(r'(?:普通\\s*)?(\\d+)\\s*\\*\\s*(\\d+)\\s*mm', s)",
                "if m:",
                "    result['width'] = m.group(1) + 'mm'",
                "    result['height'] = m.group(2) + 'mm'",
            ],
        })

    # 6. 瓷砖W*H*amm（带厚度）
    m3d = re.match(r"(?:普通\s*)?(\d+)\s*\*\s*(\d+)\s*\*\s*(\d+)\s*mm", s)
    if m3d and wid and thick:
        rules.append({
            "attr": "width",
            "note": f"瓷砖W*H*T: {spec}",
            "code_lines": [
                "m = re.search(r'(?:普通\\s*)?(\\d+)\\s*\\*\\s*(\\d+)\\s*\\*\\s*(\\d+)\\s*mm', s)",
                "if m:",
                "    result['width'] = m.group(1) + 'mm'",
                "    result['height'] = m.group(2) + 'mm'",
                "    result['thickness'] = m.group(3) + 'mm'",
            ],
        })

    # 7. 金属W*H重型
    if re.match(r"\d+\s*\*\s*\d+\s*重型", s) and wid:
        rules.append({
            "attr": "width",
            "note": f"金属材料: {spec}",
            "code_lines": [
                "m = re.search(r'(\\d+)\\s*\\*\\s*(\\d+)\\s*重型', s)",
                "if m:",
                "    result['width'] = m.group(1) + 'mm'",
                "    result['height'] = m.group(2) + 'mm'",
            ],
        })

    return rules


def try_insert(rule: dict) -> bool:
    """将 rule 插入 base.py，通过验证则保留"""
    attr = rule["attr"]
    note = rule["note"]
    code_lines = rule["code_lines"]

    with open(BASE_PY) as f:
        content = f.read()

    bak = str(BASE_PY) + ".bak"
    shutil.copy(BASE_PY, bak)

    # 生成带缩进的代码块
    indent = "        "
    block = "\n".join(f"{indent}{ln}" for ln in code_lines)
    comment = f"{indent}# ── 自动生成: {note} ──"

    insert_after = get_insert_after_line(content, attr)
    lines = content.splitlines()
    lines.insert(insert_after + 1, comment)
    lines.insert(insert_after + 2, block)
    new_content = "\n".join(lines)

    # 语法检查
    try:
        compile(new_content, str(BASE_PY), "exec")
    except SyntaxError as e:
        print(f"  ⚠️  语法错误: {e}")
        return False

    with open(BASE_PY, "w") as f:
        f.write(new_content)

    passed, total = run_validate()
    ok = (passed == total and total > 0)

    if ok:
        os.remove(bak)
        print(f"  ✅ {passed}/{total} 通过，写入成功（base.py 第{insert_after + 2}行后）")
    else:
        shutil.move(bak, BASE_PY)
        print(f"  ❌ {passed}/{total} 不通过，rollback")

    return ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True)
    parser.add_argument("--expected", required=True)
    args = parser.parse_args()

    expected = json.loads(args.expected)
    spec = args.spec.strip()

    print(f"\n─── [{spec}] → {expected}")

    rules = patterns_for(spec, expected)
    if not rules:
        print("❌ 无法为此 spec 生成规则")
        return 1

    for rule in rules:
        print(f"\n尝试: {rule['note']}")
        ok = try_insert(rule)
        if ok:
            return 0

    print("\n⚠️  所有候选均未通过验证")
    return 1


if __name__ == "__main__":
    sys.exit(main())
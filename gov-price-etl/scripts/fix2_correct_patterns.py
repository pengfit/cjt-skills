#!/usr/bin/env python3
"""fix2_correct_patterns.py - 第二轮修复：用正确的 regex 补 ΦDx*Dx 和 DNx+MPa 规则

修复点：
1. ΦDx*Dx 现有规则用 × (中文乘号) 而 spec 用 * (ASCII 星号) → 用 [*×xX] 兼容
2. DNx+MPa 现有规则贪婪匹配把 pressure 吃进 diameter → 用 (?:\d+\.\d+Mpa)? 强制小数点
3. 阀门型号 Pattern D 只解 model → 加 diameter/pressure 提取
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from gov_price_etl.parse_spec.rules.vector_store import get_vec_store

NOTE = "fix2_correct_regex_2026-07-18"

# (pattern, attr, code_block, l3)
# 关键: L3 必须是 DWD 实际分布的编码
RULES = [
    # ── A. ΦDx*Dx 钢管（兼容 *, ×, x, X, ＊, ╳）──
    # L3: 03.01.01 (27), 03.01.03 (15), 04.07.02 (15)
    *[(r'^Φ?\s*(\d+(?:\.\d+)?)\s*[*×xX＊*╳]\s*(\d+(?:\.\d+)?)\s*(.*)$',
       'diameter',
       'm = re.match(r"^Φ?\\s*(\\d+(?:\\.\\d+)?)\\s*[*×xX＊*╳]\\s*(\\d+(?:\\.\\d+)?)\\s*(.*)$", s)\n'
       'if m:\n'
       '    result["diameter"] = m.group(1) + "mm"\n'
       '    if m.group(3).strip():\n'
       '        result["note"] = m.group(3).strip()',
       l3)
      for l3 in ['03.01.01', '03.01.03', '04.07.02']],
    *[(r'^Φ?\s*(\d+(?:\.\d+)?)\s*[*×xX＊*╳]\s*(\d+(?:\.\d+)?)\s*(.*)$',
       'wall_thickness',
       'm = re.match(r"^Φ?\\s*(\\d+(?:\\.\\d+)?)\\s*[*×xX＊*╳]\\s*(\\d+(?:\\.\\d+)?)\\s*(.*)$", s)\n'
       'if m:\n'
       '    result["wall_thickness"] = m.group(2) + "mm"',
       l3)
      for l3 in ['03.01.01', '03.01.03', '04.07.02']],

    # ── B. DNx 修正（含 MPa 但用小数点后回溯，让 diameter 留在前面）──
    # L3: 03.05.01 (30), 03.01.04 (21), 06.03.02 (9), 03.04.02 (3)
    *[(r'^DN(\d+)(?:(\d+(?:\.\d+)?)Mpa)?$',
       'diameter',
       'm = re.match(r"^DN(\\d+)(?:(\\d+(?:\\.\\d+)?)Mpa)?$", s, re.IGNORECASE)\n'
       'if m:\n'
       '    result["diameter"] = m.group(1) + "mm"',
       l3)
      for l3 in ['03.05.01', '03.01.04', '06.03.02', '03.04.02']],
    *[(r'^DN(\d+)(?:(\d+(?:\.\d+)?)Mpa)?$',
       'pressure',
       'm = re.match(r"^DN(\\d+)(?:(\\d+(?:\\.\\d+)?)Mpa)?$", s, re.IGNORECASE)\n'
       'if m and m.group(2):\n'
       '    result["pressure"] = m.group(2) + "MPa"',
       l3)
      for l3 in ['03.05.01', '03.01.04', '06.03.02', '03.04.02']],

    # ── C. 阀门型号 JxxH-xCDNxxx（修正：model + diameter + pressure 三件套）──
    # L3: 03.05.01 (阀门), 03.01.04 (法兰)
    *[(r'^([A-Z]\d+[A-Z]?(?:-\d+[A-Z]?)?)(?:DN(\d+)(?:\.?(\d+(?:\.\d+)?)Mpa)?)?$',
       'model',
       'm = re.match(r"^([A-Z]\\d+[A-Z]?(?:-\\d+[A-Z]?)?)(?:DN(\\d+)(?:\\.?(\\d+(?:\\.\\d+)?)Mpa)?)?$", s)\n'
       'if m and m.group(1):\n'
       '    result["model"] = m.group(1)',
       l3)
      for l3 in ['03.05.01', '03.01.04']],
    *[(r'^(?:[A-Z]\d+[A-Z]?(?:-\d+[A-Z]?)?)?(?:DN(\d+)(?:\.?(\d+(?:\.\d+)?)Mpa)?)?$',
       'diameter',
       'm = re.match(r"^(?:[A-Z]\\d+[A-Z]?(?:-\\d+[A-Z]?)?)?(?:DN(\\d+)(?:\\.?(\\d+(?:\\.\\d+)?)Mpa)?)?$", s)\n'
       'if m and m.group(1):\n'
       '    result["diameter"] = m.group(1) + "mm"',
       l3)
      for l3 in ['03.05.01', '03.01.04']],
    *[(r'^(?:[A-Z]\d+[A-Z]?(?:-\d+[A-Z]?)?)?(?:DN(\d+)(?:\.?(\d+(?:\.\d+)?)Mpa)?)?$',
       'pressure',
       'm = re.match(r"^(?:[A-Z]\\d+[A-Z]?(?:-\\d+[A-Z]?)?)?(?:DN(\\d+)(?:\\.?(\\d+(?:\\.\\d+)?)Mpa)?)?$", s)\n'
       'if m and m.group(2):\n'
       '    result["pressure"] = m.group(2) + "MPa"',
       l3)
      for l3 in ['03.05.01', '03.01.04']],

    # ── D. K9DNx 球墨铸铁管（追加，确保 03.01.01 L3 命中）──
    *[(r'^(K\d+)DN(\d+)$',
       'wall_grade',
       'm = re.match(r"^(K\\d+)DN(\\d+)$", s)\n'
       'if m:\n'
       '    result["wall_grade"] = m.group(1)',
       l3)
      for l3 in ['03.01.01']],
    *[(r'^(K\d+)DN(\d+)$',
       'diameter',
       'm = re.match(r"^(K\\d+)DN(\\d+)$", s)\n'
       'if m:\n'
       '    result["diameter"] = m.group(2) + "mm"',
       l3)
      for l3 in ['03.01.01']],

    # ── E. BV/NH-BV/ZR-BV 线缆（修复：兼容更多前缀）──
    # L3: 04.07.01 (电气)
    *[(r'^(ZR|NH|WE|FS|YD)?-?(BV|BVR|BVV|RV|RVV)(\d+(?:\.\d+)?)$',
       'insulation',
       'm = re.match(r"^(ZR|NH|WE|FS|YD)?-?(BV|BVR|BVV|RV|RVV)(\\d+(?:\\.\\d+)?)$", s)\n'
       'if m and m.group(1):\n'
       '    result["insulation"] = m.group(1)',
       l3)
      for l3 in ['04.07.01']],
    *[(r'^(ZR|NH|WE|FS|YD)?-?(BV|BVR|BVV|RV|RVV)(\d+(?:\.\d+)?)$',
       'cross_section_area',
       'm = re.match(r"^(ZR|NH|WE|FS|YD)?-?(BV|BVR|BVV|RV|RVV)(\\d+(?:\\.\\d+)?)$", s)\n'
       'if m and m.group(3):\n'
       '    result["cross_section_area"] = m.group(3) + "mm²"',
       l3)
      for l3 in ['04.07.01']],

    # ── F. HDPE DNxSNx ──
    # L3: 07.03.02
    *[(r'^DN(\d+)(SN\d+)$',
       'diameter',
       'm = re.match(r"^DN(\\d+)(SN\\d+)$", s)\n'
       'if m:\n'
       '    result["diameter"] = m.group(1) + "mm"',
       l3)
      for l3 in ['07.03.02']],
    *[(r'^DN(\d+)(SN\d+)$',
       'ring_stiffness',
       'm = re.match(r"^DN(\\d+)(SN\\d+)$", s)\n'
       'if m:\n'
       '    result["ring_stiffness"] = m.group(2)',
       l3)
      for l3 in ['07.03.02']],
]


def main():
    vs = get_vec_store()

    inserted = 0
    duplicate = 0
    by_pattern = {}
    for pattern, attr, code, l3 in RULES:
        ok = vs.insert(
            pattern=pattern,
            attr=attr,
            code=code,
            breed="",
            category="",
            l3=l3,
            note=NOTE,
            skip_duplicate=True,
        )
        key = (pattern[:30], l3, attr)
        if ok:
            inserted += 1
            by_pattern[key] = by_pattern.get(key, 0) + 1
        else:
            duplicate += 1

    print("=" * 60)
    print(f"第二轮修复规则入库:")
    print(f"  ✓ 新插入: {inserted}")
    print(f"  ⊘ 重复跳过: {duplicate}")
    print(f"  总定义: {len(RULES)}")
    print()
    print("按 (pattern, l3, attr) 新插入明细:")
    for key in sorted(by_pattern.keys()):
        print(f"  {key}")


if __name__ == "__main__":
    main()

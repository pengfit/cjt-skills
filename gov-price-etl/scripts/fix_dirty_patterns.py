#!/usr/bin/env python3
"""fix_dirty_patterns.py - 给威海脏数据模式补规则

针对 166 条单键 attr 的规则残缺问题，按 (pattern × L3 × attr) 三维入库。
L3 必须用编码（用户约束），每条规则通过 L3 加权召回精准命中对应记录。
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from gov_price_etl.parse_spec.rules.vector_store import get_vec_store

NOTE = "fix_weihai_dirty_2026-07-18"

# 规则定义: (pattern, attr, code_block, l3)
# L3 来自 DWD Weihai 实际分布（已查询）
RULES = [
    # ── 模式 A: ΦDx*Dx 钢管 (11 条) ──
    # L3: 03.01.01, 03.01.03, 04.07.02
    *[(r'^Φ?(\d+(?:\.\d+)?)\*(\d+(?:\.\d+)?)',
       'diameter',
       'm = re.match(r"^Φ?(\\d+(?:\\.\\d+)?)\\*(\\d+(?:\\.\\d+)?)", s)\n'
       'if m: result["diameter"] = m.group(1) + "mm"',
       l3)
      for l3 in ['03.01.01', '03.01.03', '04.07.02']],
    *[(r'^Φ?(\d+(?:\.\d+)?)\*(\d+(?:\.\d+)?)',
       'wall_thickness',
       'm = re.match(r"^Φ?(\\d+(?:\\.\\d+)?)\\*(\\d+(?:\\.\\d+)?)", s)\n'
       'if m: result["wall_thickness"] = m.group(2) + "mm"',
       l3)
      for l3 in ['03.01.01', '03.01.03', '04.07.02']],

    # ── 模式 B: K9DNx 球墨铸铁管 (9 条) ──
    *[(r'^(K\d+)DN(\d+)',
       'wall_grade',
       'm = re.match(r"^(K\\d+)DN(\\d+)", s)\n'
       'if m: result["wall_grade"] = m.group(1)',
       l3)
      for l3 in ['03.01.01']],  # 球墨铸铁管属给排水
    *[(r'^(K\d+)DN(\d+)',
       'diameter',
       'm = re.match(r"^(K\\d+)DN(\\d+)", s)\n'
       'if m: result["diameter"] = m.group(2) + "mm"',
       l3)
      for l3 in ['03.01.01']],

    # ── 模式 C: DNx+MPa 阀门/法兰/橡胶接头 (41+22 条) ──
    # L3: 03.05.01, 03.01.04, 06.03.02, 03.04.02
    *[(r'^DN(\d+)(?:\.?(\d+(?:\.\d+)?)Mpa)?',
       'diameter',
       'm = re.match(r"^DN(\\d+)(?:\\.?(\\d+(?:\\.\\d+)?)Mpa)?", s, re.IGNORECASE)\n'
       'if m: result["diameter"] = m.group(1) + "mm"',
       l3)
      for l3 in ['03.05.01', '03.01.04', '06.03.02', '03.04.02']],
    *[(r'^DN(\d+)(?:\.?(\d+(?:\.\d+)?)Mpa)?',
       'pressure',
       'm = re.match(r"^DN(\\d+)(?:\\.?(\\d+(?:\\.\\d+)?)Mpa)?", s, re.IGNORECASE)\n'
       'if m and m.group(2): result["pressure"] = m.group(2) + "MPa"',
       l3)
      for l3 in ['03.05.01', '03.01.04', '06.03.02', '03.04.02']],

    # ── 模式 D: 阀门型号 JxxH-xCDNxxx (63 条,合并到上面 C) ──
    # 注：JxxH-xCDNxxx 实际是先匹配到 DN+MPa 拿 diameter/pressure，
    #    但 model 字段漏解。可加额外模式提取 model。
    *[(r'^([A-Z]\d+[A-Z]?(?:-\d+[A-Z]?)?)DN(\d+)',
       'model',
       'm = re.match(r"^([A-Z]\\d+[A-Z]?(?:-\\d+[A-Z]?)?)DN(\\d+)", s)\n'
       'if m: result["model"] = m.group(1)',
       l3)
      for l3 in ['03.05.01', '03.01.04']],

    # ── 模式 E: BVx / NH-BV / ZR-BV 线缆 (12 条) ──
    # L3: 04.07.01
    *[(r'^(?:(ZR|NH|WE|FS|YD)-)?(BV|BVR|BVV|RV|RVV)(\d+(?:\.\d+)?)$',
       'insulation',
       'm = re.match(r"^(?:(ZR|NH|WE|FS|YD)-)?(BV|BVR|BVV|RV|RVV)(\\d+(?:\\.\\d+)?)$", s)\n'
       'if m and m.group(1): result["insulation"] = m.group(1)',
       l3)
      for l3 in ['04.07.01']],
    *[(r'^(?:(ZR|NH|WE|FS|YD)-)?(BV|BVR|BVV|RV|RVV)(\d+(?:\.\d+)?)$',
       'cross_section_area',
       'm = re.match(r"^(?:(ZR|NH|WE|FS|YD)-)?(BV|BVR|BVV|RV|RVV)(\\d+(?:\\.\\d+)?)$", s)\n'
       'if m: result["cross_section_area"] = m.group(3) + "mm²"',
       l3)
      for l3 in ['04.07.01']],

    # ── 模式 F: HDPE DNxSNx (4 条) ──
    # L3: 07.03.02
    *[(r'^DN(\d+)(SN\d+)$',
       'diameter',
       'm = re.match(r"^DN(\\d+)(SN\\d+)$", s)\n'
       'if m: result["diameter"] = m.group(1) + "mm"',
       l3)
      for l3 in ['07.03.02']],
    *[(r'^DN(\d+)(SN\d+)$',
       'ring_stiffness',
       'm = re.match(r"^DN(\\d+)(SN\\d+)$", s)\n'
       'if m: result["ring_stiffness"] = m.group(2)',
       l3)
      for l3 in ['07.03.02']],

    # ── 模式 G: 铝单板 / 复合保温外墙板 喷涂+mm (3 条) ──
    # L3: 01.05.05, 02.02.09
    *[(r'^(.+?)[，,]\s*(\d+(?:\.\d+)?)\s*mm$',
       'surface',
       'm = re.match(r"^(.+?)[，,]\\s*(\\d+(?:\\.\\d+)?)\\s*mm$", s)\n'
       'if m: result["surface"] = m.group(1)',
       l3)
      for l3 in ['01.05.05', '02.02.09']],
    *[(r'^(.+?)[，,]\s*(\d+(?:\.\d+)?)\s*mm$',
       'thickness',
       'm = re.match(r"^(.+?)[，,]\\s*(\\d+(?:\\.\\d+)?)\\s*mm$", s)\n'
       'if m: result["thickness"] = m.group(2) + "mm"',
       l3)
      for l3 in ['01.05.05', '02.02.09']],
]


def main():
    vs = get_vec_store()

    inserted = 0
    duplicate = 0
    failed = 0
    by_pattern_l3 = {}

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
        key = (pattern[:25], l3)
        if ok:
            inserted += 1
            by_pattern_l3[key] = by_pattern_l3.get(key, 0) + 1
        else:
            duplicate += 1

    print("=" * 60)
    print(f"修复规则入库结果:")
    print(f"  ✓ 新插入: {inserted}")
    print(f"  ⊘ 重复跳过: {duplicate}")
    print(f"  ✗ 失败: {failed}")
    print()
    print(f"按 (pattern, l3) 统计:")
    for (pat, l3), n in sorted(by_pattern_l3.items()):
        print(f"  {pat}... @ {l3}: {n} 条 attr")
    print()
    print(f"总规则定义: {len(RULES)} 条 = {len(RULES) // 2} 个模式 × 2 个 attr")


if __name__ == "__main__":
    main()

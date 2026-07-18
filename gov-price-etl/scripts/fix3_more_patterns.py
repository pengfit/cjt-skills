#!/usr/bin/env python3
"""fix3_more_patterns.py - 第三轮修复：批量补单键规则

按 354 条单键 pattern 归类，聚焦 ≥5 条 + 形态清晰的模式：
- Mx_strength_qual (14 条): 强度等级M5/M7.5/M10
- K9DNx (9 条): K9DN200/K9DN300 (已有规则, 复查)
- NH-BVx_cable (7): ZR-BV4/NH-BV16 (已有规则, 复查)
- BVx_cable (5): BV4/BV6/BV10 (已有规则, 复查)
- Px_pressure (2): P6/P10 (已有规则, 复查)
- ΦDx*Dx_pipe (18): Φ76*4 (已有规则, stage 2 没真 fire, 加更多变体)
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from gov_price_etl.parse_spec.rules.vector_store import get_vec_store

NOTE = "fix3_pattern_classify_2026-07-18"

RULES = []

# ── A. 强度等级 M5/M7.5/M10 ── (14 条, L3: 02.02.01 抹灰砂浆, 01.04.01 砌筑砂浆)
# pattern 兼容 'M5', 'M7.5', '强度等级M5', '强度等级 M7.5' (有空格)
for l3 in ['02.02.01', '01.04.01', '01.08.02']:
    RULES.append((
        r'^(?:强度等级)?\s*(M\d+(?:\.\d+)?)\s*$',
        'strength',
        'm = re.match(r"^(?:强度等级)?\\s*(M\\d+(?:\\.\\d+)?)\\s*$", s)\n'
        'if m:\n'
        '    result["strength"] = m.group(1)',
        l3,
    ))

# ── B. K9DNx 球墨铸铁管 ── (9 条, L3=03.01.01) - 已有规则, 加强正则
RULES.append((
    r'^(K\d+)DN(\d+)$',
    'wall_grade',
    'm = re.match(r"^(K\\d+)DN(\\d+)$", s)\n'
    'if m:\n'
    '    result["wall_grade"] = m.group(1)',
    '03.01.01',
))
RULES.append((
    r'^(K\d+)DN(\d+)$',
    'diameter',
    'm = re.match(r"^(K\\d+)DN(\\d+)$", s)\n'
    'if m:\n'
    '    result["diameter"] = m.group(2) + "mm"',
    '03.01.01',
))

# ── C. 线缆 BV/NH-BV/ZR-BV ── (12 条, L3=04.07.01)
# 已有规则, 加强: 把 prefix 当 insulation, 也支持更多 prefix
for l3 in ['04.07.01']:
    RULES.append((
        r'^(ZR|NH|WE|FS|YD)?-?(BV|BVR|BVV|RV|RVV)(\d+(?:\.\d+)?)\s*(?:mm²)?$',
        'insulation',
        'm = re.match(r"^(ZR|NH|WE|FS|YD)?-?(BV|BVR|BVV|RV|RVV)(\\d+(?:\\.\\d+)?)\\s*(?:mm²)?$", s)\n'
        'if m and m.group(1):\n'
        '    result["insulation"] = m.group(1)',
        l3,
    ))
    RULES.append((
        r'^(ZR|NH|WE|FS|YD)?-?(BV|BVR|BVV|RV|RVV)(\d+(?:\.\d+)?)\s*(?:mm²)?$',
        'cross_section_area',
        'm = re.match(r"^(ZR|NH|WE|FS|YD)?-?(BV|BVR|BVV|RV|RVV)(\\d+(?:\\.\\d+)?)\\s*(?:mm²)?$", s)\n'
        'if m:\n'
        '    result["cross_section_area"] = m.group(2) + "mm²"',
        l3,
    ))

# ── D. 抗渗等级 P6/P10 ── (2 条, L3=09.07.01)
# 之前错识为 width, 应是 permeability_grade
RULES.append((
    r'^P(\d+(\.\d+)?)$',
    'permeability_grade',
    'm = re.match(r"^P(\\d+(\\.\\d+)?)$", s)\n'
    'if m:\n'
    '    result["permeability_grade"] = "P" + m.group(1)',
    '09.07.01',
))

# ── E. 单段 ΦDx (直径, 无厚度) ── (~7 条, 多 L3) - 已有规则, 加强
# 这些就是单纯 'Φ76' 这种, 只有 diameter 是正确 attr
# 单键本来就是对的, 不需要补

# ── F. 单段 DNx (直径, 无压力) ── (~56 条, 多 L3) - 已有规则, 单键就是对的
# 单键本来就是对的, 不需要补

# ── G. 防火门 grade 甲级/乙级/丙级 ── (~6 条)
RULES.append((
    r'^(甲|乙|丙)级$',
    'grade',
    'm = re.match(r"^(甲|乙|丙)级$", s)\n'
    'if m:\n'
    '    result["grade"] = m.group(1) + "级"',
    '04.05.01',  # 防火门类
))

# ── H. 120KN 类压力等级 ── (玻纤格栅 2 条, L3=01.02.01)
RULES.append((
    r'^(\d+(?:\.\d+)?)(KN|kN)$',
    'load_capacity',
    'm = re.match(r"^(\\d+(?:\\.\\d+)?)(KN|kN)$", s)\n'
    'if m:\n'
        '    result["load_capacity"] = m.group(1) + m.group(2).upper()',
    '01.02.01',
))

# ── I. 50*50厚度0.8mm 类桥架 ── (~6 条, L3=04.07.02)
# 这种 'W*H厚度Tmm' 复合 spec 比较复杂, 先跳过(等专门处理)


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
        key = (attr, l3)
        if ok:
            inserted += 1
            by_pattern[key] = by_pattern.get(key, 0) + 1
        else:
            duplicate += 1

    print("=" * 60)
    print(f"第三轮修复规则入库:")
    print(f"  ✓ 新插入: {inserted}")
    print(f"  ⊘ 重复跳过: {duplicate}")
    print(f"  总定义: {len(RULES)}")
    print()
    print("按 (attr, l3) 新插入明细:")
    for k, v in sorted(by_pattern.items()):
        print(f"  {k}: {v} 条")


if __name__ == "__main__":
    main()

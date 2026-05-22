# grade 规则文件 - 由 migrate_rules.py 生成

# ── 自动生成: 水泥等级: 袋装P.S.A ──
m = re.search(r'袋装\s*P\.S\.A\s*(\d+\.?\d*)', s)
if m:
    result['grade'] = 'P.S.A' + m.group(1)

# ── 自动生成: 保温等级+干密度: B*级干密度 ──
m = re.search(r'(B\d)级.*?干密度(\d+)\s*kg/m3', s)
if m:
    result['grade'] = m.group(1) + '级'
    result['material'] = '干密度' + m.group(2) + 'kg/m3'


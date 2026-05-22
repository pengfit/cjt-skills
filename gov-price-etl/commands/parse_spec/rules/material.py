# material 规则文件 - 由 migrate_rules.py 生成

# ── 自动生成: 钢材SF型号: SFN ──
m = re.search(r'^(SF\d+)', s)
if m:
    result['material'] = m.group(1)


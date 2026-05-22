# cores 规则文件 - 由 migrate_rules.py 生成

# ── 自动生成: 光纤芯数: N芯 ──
m = re.search(r'(\d+)芯', s)
if m:
    result['cores'] = m.group(1) + '芯'


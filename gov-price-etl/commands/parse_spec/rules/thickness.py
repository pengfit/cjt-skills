# thickness 规则文件 - 由 migrate_rules.py 生成

# ── 自动生成: 板厚: 板叠厚Xmm ──
m = re.search(r'板[叠厚]?(\d+(?:\.\d+)?)\s*mm', s)
if m:
    result['thickness'] = m.group(1) + 'mm'


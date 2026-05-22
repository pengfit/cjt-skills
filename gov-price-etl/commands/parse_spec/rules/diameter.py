# diameter 规则文件 - 由 migrate_rules.py 生成

# ── 自动生成: 钢管 D*N*N: D*N*N ──
m = re.search(r'^D(\d+)\*(\d+)$', s)
if m:
    result['diameter'] = 'D' + m.group(1)
    result['thickness'] = m.group(2) + 'mm'

# ── 自动生成: JDG管: JDGΦ ──
m = re.search(r'JDGΦ(\d+)\*(\d+(?:\.\d+)?)\s*mm', s)
if m:
    result['diameter'] = 'Φ' + m.group(1)
    result['thickness'] = m.group(2) + 'mm'

# ── 自动生成: Φ管径+壁厚: ΦN*Nmm ──
m = re.search(r'Φ(\d+)\*(\d+(?:\.\d+)?)\s*mm', s)
if m:
    result['diameter'] = 'Φ' + m.group(1)
    result['thickness'] = m.group(2) + 'mm'


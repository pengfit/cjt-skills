# width 规则文件 - 由 migrate_rules.py 生成

# ── 自动生成: 瓷砖W*H*T: W*H*Tmm ──
m = re.search(r'(?:普通\s*)?(\d+)\s*\*\s*(\d+)\s*\*\s*(\d+)\s*mm$', s)
if m:
    result['width'] = m.group(1) + 'mm'
    result['height'] = m.group(2) + 'mm'
    result['thickness'] = m.group(3) + 'mm'

# ── 自动生成: 瓷砖W*H: W*Hmm ──
m = re.search(r'(?:普通\s*)?(\d+)\s*\*\s*(\d+)\s*mm$', s)
if m:
    result['width'] = m.group(1) + 'mm'
    result['height'] = m.group(2) + 'mm'

# ── 自动生成: 金属材料: W*H重型 ──
m = re.search(r'(\d+)\s*\*\s*(\d+)\s*重型', s)
if m:
    result['width'] = m.group(1) + 'mm'
    result['height'] = m.group(2) + 'mm'

# ── 自动生成: 尺寸A*B*C(L): A*B*C(L) ──
m = re.search(r'(\d+)\s*\*\s*(\d+)\s*\*\s*(\d+)\s*\([Lℓ]\)', s)
if m:
    result['width'] = m.group(1) + 'mm'
    result['height'] = m.group(2) + 'mm'
    result['thickness'] = m.group(3) + 'mm'


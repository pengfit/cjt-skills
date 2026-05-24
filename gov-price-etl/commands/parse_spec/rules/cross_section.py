
# ── 自动生成: 电缆截面 1.5mm² ──
m = re.search(r'×(\d+(?:\.\d+)?)\s*mm2', s)
if m:
    result['cross_section'] = m.group(1) + 'mm²'

# ── 自动生成: 电缆截面 4mm² ──
m = re.search(r'×(\d+(?:\.\d+)?)\s*mm2', s)
if m:
    result['cross_section'] = m.group(1) + 'mm²'

# ── 自动生成: 电缆截面 50mm² ──
m = re.search(r'×(\d+(?:\.\d+)?)\s*mm2', s)
if m:
    result['cross_section'] = m.group(1) + 'mm²'

# ── 自动生成: 电缆截面 50mm² ──
m = re.search(r'×(\d+(?:\.\d+)?)\s*mm2', s)
if m:
    result['cross_section'] = m.group(1) + 'mm²'

# ── 自动生成: 电缆单芯截面 1.5mm² ──
m = re.search(r'×2×(\d+(?:\.\d+)?)\s*mm2', s)
if m:
    result['cross_section'] = m.group(1) + 'mm²'

# ── 自动生成: 电缆截面 6mm² ──
m = re.search(r'×(\d+(?:\.\d+)?)\s*mm2', s)
if m:
    result['cross_section'] = m.group(1) + 'mm²'

# ── 自动生成: 主截面 150mm² ──
m = re.search(r'^\d+×(\d+)\+', s)
if m:
    result['cross_section'] = m.group(1) + 'mm²'

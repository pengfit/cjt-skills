# length.py - 长度规则

# ── 自动生成: 长度前缀 长度1200 ──
m = re.search(r'^长度(\d+)$', s, re.IGNORECASE)
if m:
    result['length'] = m.group(1) + 'mm'

# ── 自动生成: 长度m/长度cm ──
m = re.search(r'^长度(\d+(?:\.\d+)?)\s*(m|cm|米|厘米)', s, re.IGNORECASE)
if m:
    val, unit = m.group(1), m.group(2)
    unit_map = {'m': 'm', 'cm': 'cm', '米': 'm', '厘米': 'cm'}
    result['length'] = val + unit_map.get(unit, unit)

# ── 自动生成: 长度范围 2.0~3.0cm ──
m = re.search(r'^(\d+(?:\.\d+)?)\s*~\s*(\d+(?:\.\d+)?)\s*(cm|m|厘米|米)', s, re.IGNORECASE)
if m:
    result['length_range'] = m.group(1) + '~' + m.group(2) + m.group(3)

# ── 自动生成: 定尺长度 mm×mm×mm(L) ──
m = re.search(r'^(\d+)\s*[×xX*]\s*(\d+)\s*[×xX*]\s*(\d+)\s*\([Lℓ]\)', s)
if m:
    result['length'] = m.group(1) + 'mm'
    result['width'] = m.group(2) + 'mm'
    result['height'] = m.group(3) + 'mm'

# ── 自动生成: 高度H= 散热器 H=0.6m (带单位，<10当mm换算) ──
m = re.search(r'^H\s*=\s*([\d.]+)\s*m$', s, re.IGNORECASE)
if m:
    val = float(m.group(1))
    if val < 10:
        result['height'] = str(int(val * 1000)) + 'mm'
    else:
        result['height'] = str(int(val)) + 'mm'

# ── 自动生成: 高度H= 散热器 H=600 (无单位，当作mm) ──
m = re.search(r'^H\s*=\s*(\d+)\s*$', s)
if m:
    result['height'] = m.group(1) + 'mm'

# ── 自动生成: 四柱散热器高度 四柱460型 H=680 ──
m = re.search(r'四柱(\d+)型\s+H\s*=\s*(\d+)', s)
if m:
    result['height'] = m.group(2) + 'mm'

# ── 自动生成: 双柱散热器高度 双柱 H=500 ──
m = re.search(r'双柱\s+H\s*=\s*(\d+)', s)
if m:
    result['height'] = m.group(1) + 'mm'

# ── 自动生成: 铝合金窗系列 85系列 70系列 ──
m = re.search(r'^(\d+)\s*系列', s)
if m:
    result['series'] = m.group(1) + '系列'

# ── 自动生成: 功率/长度复合 功率4.8W/m 长度300mm ──
m = re.search(r'^功率[\d.]+\s*W[/m]?\s*长度\s*(\d+)\s*mm', s)
if m:
    result['length'] = m.group(1) + 'mm'

# ── 自动生成: 功率W ──
m = re.search(r'^(\d+(?:\.\d+)?)\s*W(?:\s|$)', s)
if m:
    result['power'] = m.group(1) + 'W'

# ── 自动生成: 玻璃厚度规格 12mm (纯厚度) ──
m = re.search(r'^(\d+(?:\.\d+)?)\s*mm$', s)
if m:
    result['thickness'] = m.group(1) + 'mm'
# ── 自动生成: 2D尺寸无后缀(3-4位) 500×150 ──
m = re.search(r'^(\d{3,4})\s*[×xX*]\s*(\d{3,4})$', s)
if m:
    result['length'] = m.group(1) + 'mm'
    result['width'] = m.group(2) + 'mm'

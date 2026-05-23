# width.py - 尺寸规则 (不含 mm 后缀的 2D/3D 尺寸)

# ── 自动生成: 3D尺寸 A×B×Cmm ──
m = re.search(r'^(\d+)\s*[×xX*]\s*(\d+)\s*[×xX*]\s*(\d+)\s*mm$', s)
if m:
    result['length'] = m.group(1) + 'mm'
    result['width'] = m.group(2) + 'mm'
    result['height'] = m.group(3) + 'mm'

# ── 自动生成: 2D尺寸 A×Bmm ──
m = re.search(r'^(\d+)\s*[×xX*]\s*(\d+)\s*mm$', s)
if m:
    result['length'] = m.group(1) + 'mm'
    result['width'] = m.group(2) + 'mm'

# ── 自动生成: 2D尺寸无后缀(3-4位) 500×150 ──
m = re.search(r'^(\d{3,4})\s*[×xX*]\s*(\d{3,4})$', s)
if m:
    result['length'] = m.group(1) + 'mm'
    result['width'] = m.group(2) + 'mm'

# ── 自动生成: 尺寸:xxx×xxx×xxxmm ──
m = re.search(r'尺寸[：:]?\s*(\d+)\s*[×xX*]\s*(\d+)\s*[×xX*]\s*(\d+)\s*mm', s)
if m:
    result['length'] = m.group(1) + 'mm'
    result['width'] = m.group(2) + 'mm'
    result['height'] = m.group(3) + 'mm'

# ── 自动生成: 尺寸:xxx×xxxmm ──
m = re.search(r'尺寸[：:]?\s*(\d+)\s*[×xX*]\s*(\d+)\s*mm', s)
if m:
    result['length'] = m.group(1) + 'mm'
    result['width'] = m.group(2) + 'mm'

# ── 自动生成: 井盖尺寸 mm×mm×mm ──
m = re.search(r'(\d+)mm×(\d+)mm×(\d+)mm', s)
if m:
    result['length'] = m.group(1) + 'mm'
    result['width'] = m.group(2) + 'mm'
    result['height'] = m.group(3) + 'mm'

# ── 自动生成: 宽度前缀 ──
m = re.search(r'^宽[度]?\s*(\d+)\s*cm', s, re.IGNORECASE)
if m:
    result['width'] = m.group(1) + 'cm'
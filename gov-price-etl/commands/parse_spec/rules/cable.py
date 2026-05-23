# cable.py - 电缆/光纤规格规则
# 注意: clean_spec 将 × 替换为 *，规格字符串如 4×16mm² → 4*16mm²

# ── 自动生成: 电缆 N×Nmm² (带字母前缀) BV-4mm² ──
m = re.search(r'^[A-Z-]+\s*[-:]?\s*(\d+)\s*[×*x]\s*(\d+(?:\.\d+)?)\s*mm[²2]$', s)
if m:
    result['cores'] = m.group(1) + '芯'
    result['cross_section'] = m.group(2) + 'mm²'

# ── 自动生成: 电缆 N×Nmm² (纯数字前缀) 4×16mm² ──
m = re.search(r'^(\d+)\s*[×*x]\s*(\d+(?:\.\d+)?)\s*mm[²2]$', s)
if m:
    result['cores'] = m.group(1) + '芯'
    result['cross_section'] = m.group(2) + 'mm²'

# ── 自动生成: 电缆 N×N+N×Nmm² YJV-3×120+1×70mm² ──
m = re.search(r'^[A-Z-]+\s*[-:]?\s*(\d+)\s*[×*x]\s*(\d+(?:\.\d+)?)\s*\+\s*\d+\s*[×*x]\s*\d+(?:\.\d+)?\s*mm[²2]$', s)
if m:
    result['cores'] = m.group(1) + '芯'
    result['cross_section'] = m.group(2) + 'mm²'

# ── 自动生成: 电缆 N×N+N×Nmm² ZR-YJV-3×95+2×50mm² ──
m = re.search(r'^[A-Z-]+\s*[-:]?\s*(\d+)\s*[×*x]\s*(\d+(?:\.\d+)?)\s*\+\s*(\d+)\s*[×*x]\s*(\d+(?:\.\d+)?)\s*mm[²2]$', s)
if m:
    result['cores'] = m.group(1) + '芯'
    result['cross_section'] = m.group(2) + 'mm²'

# ── 自动生成: 电缆 3×120mm² (无加芯截面) ──
m = re.search(r'^[A-Z-]+\s*[-:]?\s*(\d+)\s*[×*x]\s*(\d+(?:\.\d+)?)\s*mm[²2]$', s)
if m:
    result['cores'] = m.group(1) + '芯'
    result['cross_section'] = m.group(2) + 'mm²'

# ── 自动生成: 芯数 4芯光纤 ──
m = re.search(r'^(\d+)\s*芯', s)
if m:
    result['cores'] = m.group(1) + '芯'

# ── 自动生成: 光纤类型 OS2 ──
m = re.search(r'(?:OS1|OS2|OM1|OM2|OM3|OM4)', s, re.IGNORECASE)
if m:
    result['fiber_type'] = m.group(0).upper()
# ring_stiffness.py - 环刚度规则

# ── 自动生成: DN + 环刚度 SN12.5 ──
m = re.search(r'^DN(\d+)\s+环刚度[≥＞]\s*SN?(\d+\.?\d*)', s, re.IGNORECASE)
if m:
    result['diameter'] = 'DN' + m.group(1)
    result['ring_stiffness'] = 'SN' + m.group(2)

# ── 自动生成: DN + 环刚度 SN8 (无≥) ──
m = re.search(r'^DN(\d+)\s+.*?\s+SN(\d+\.?\d*)', s)
if m:
    result['diameter'] = 'DN' + m.group(1)
    result['ring_stiffness'] = 'SN' + m.group(2)

# ── 自动生成: 环刚度 SN12.5 独立 ──
m = re.search(r'环刚度[≥＞]\s*SN?(\d+\.?\d*)', s, re.IGNORECASE)
if m:
    result['ring_stiffness'] = 'SN' + m.group(1)

# ── 自动生成: 独立 SN8 ──
m = re.search(r'^SN(\d+\.?\d*)$', s, re.IGNORECASE)
if m:
    result['ring_stiffness'] = 'SN' + m.group(1)
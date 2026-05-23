
# ── 自动生成: 提取高度H=600 ──
m = re.search(r'H=(\d+)', s)
if m:
    result['height'] = m.group(1)

# ── 自动生成: 提取高度mm ──
m = re.search(r'\*\d+mm\*(\d+)mm', s)
if m:
    result['height'] = m.group(1)

# ── 自动生成: 提取高度mm ──
m = re.search(r'^\d+\*(\d+)\*', s)
if m:
    result['height'] = m.group(1)

# ── 自动生成: 提取网孔高度mm ──
m = re.search(r'规格\d+\*(\d+)mm', s)
if m:
    result['height'] = m.group(1)

# ── 自动生成: 提取网孔高度mm ──
m = re.search(r'规格\d+\*(\d+)mm', s)
if m:
    result['height'] = m.group(1)


# ── 自动生成: 外形尺寸≤750×750，第一数字表示宽度上限 ──
m = re.search(r'≤(\d+)×(\d+)', s)
if m:
    result['width'] = m.group(1)

# ── 自动生成: 1000×500 表示宽×高尺寸，1000 为宽度 ──
m = re.search(r'(\d+)×(\d+)', s)
if m:
    result['width'] = m.group(1)

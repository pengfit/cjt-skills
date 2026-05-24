
# ── 自动生成: 外形尺寸≤750×750，第二数字表示高度上限 ──
m = re.search(r'≤(\d+)×(\d+)', s)
if m:
    result['height'] = m.group(2)

# ── 自动生成: 1000×500 表示宽×高尺寸，500 为高度 ──
m = re.search(r'(\d+)×(\d+)', s)
if m:
    result['height'] = m.group(2)

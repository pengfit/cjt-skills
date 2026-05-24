
# ── 自动生成: 应急供电时间 60min ──
m = re.search(r'(\d+)\s*(?:min|分钟)', s)
if m:
    result['range'] = m.group(1) + 'min'

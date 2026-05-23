
# ── 自动生成: 提取厚度mm ──
m = re.search(r'^\d+\*\d+\*(\d+)$', s)
if m:
    result['thickness'] = m.group(1)

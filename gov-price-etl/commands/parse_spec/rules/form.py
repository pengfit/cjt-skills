
# ── 自动生成: 提取柱型，四柱 ──
m = re.search(r'^(四柱|三柱|双柱|单柱)', s)
if m:
    result['form'] = m.group(1)

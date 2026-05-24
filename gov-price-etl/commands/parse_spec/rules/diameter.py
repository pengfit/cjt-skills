
# ── 自动生成: DN25 表示公称口径 25mm，括号内为英制对应 ──
m = re.search(r'DN(\d+)', s)
if m:
    result['diameter'] = 'DN' + m.group(1)

# ── 自动生成: 100 为公称口径 DN100 ──
m = re.search(r'^\D*?(\d+)', s)
if m:
    result['diameter'] = 'DN' + m.group(1)

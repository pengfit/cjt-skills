
# ── 自动生成: 1.2MPa 表示公称压力 ──
m = re.search(r'(\d+(?:\.\d+)?)\s*MPa', s)
if m:
    result['pressure'] = m.group(1) + 'MPa'

# ── 自动生成: 1.6 表示公称压力 1.6MPa ──
m = re.search(r'-(\d+(?:\.\d+)?)\s*(?:MPa)?\s*$', s)
if m:
    result['pressure'] = m.group(1) + 'MPa'

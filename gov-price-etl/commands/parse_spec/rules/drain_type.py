
# ── 自动生成: 后出表示排水形式为后排出水 ──
m = re.search(r'(后出|下出|上出|地出|左出|右出)', s)
if m:
    result['drain_type'] = m.group(1)

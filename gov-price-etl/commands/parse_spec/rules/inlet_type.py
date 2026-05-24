
# ── 自动生成: 后进表示进水方式为后进式 ──
m = re.search(r'(后进|侧进|底进|上进|左进|右进)', s)
if m:
    result['inlet_type'] = m.group(1)

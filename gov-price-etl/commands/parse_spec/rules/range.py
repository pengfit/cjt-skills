
# ── 自动生成: 干粉剂量3~5kg表示灭火剂充装量范围 ──
m = re.search(r'干粉剂量[：:]\s*(\d+(?:\.\d+)?)~(\d+(?:\.\d+)?)\s*kg', s)
if m:
    result['range'] = m.group(1) + '~' + m.group(2) + 'kg'

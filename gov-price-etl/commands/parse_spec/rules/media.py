
# ── 自动生成: 单模表示光纤类型为单模（SM），相对多模（MM） ──
m = re.search(r'(单模|多模)', s)
if m:
    result['media'] = m.group(1)

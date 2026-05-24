
# ── 自动生成: 86型 标准规格等级 ──
m = re.search(r'^(\d+型)', s)
if m:
    result['grade'] = m.group(1)


# ── 自动生成: I型表示产品等级/类型 ──
m = re.search(r'(I型|II型|III型|IV型|V型)', s)
if m:
    result['grade'] = m.group(1)

# ── 自动生成: 乙级表示等级/档次 ──
m = re.search(r'(甲级|乙级|丙级|丁级|特级|一级|二级|三级)', s)
if m:
    result['grade'] = m.group(1)

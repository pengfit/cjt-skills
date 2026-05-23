
# ── 自动生成: 提取强度MPa ──
m = re.search(r'>(\d+(?:\.\d+)?)\s*MPa', s)
if m:
    result['pressure'] = m.group(1) + 'MPa'

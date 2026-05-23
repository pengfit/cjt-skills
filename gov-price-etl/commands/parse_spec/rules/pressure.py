
# ── 自动生成: 提取强度MPa ──
m = re.search(r'>(\d+(?:\.\d+)?)\s*MPa', s)
if m:
    result['pressure'] = m.group(1) + 'MPa'

# ── 自动生成: 提取强度KN/m ──
m = re.search(r'强度(\d+(?:\.\d+)?)\s*KN/m', s)
if m:
    result['pressure'] = m.group(1) + 'KN/m'

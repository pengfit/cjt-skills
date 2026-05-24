# parse_spec/rules/dimension.py - 通用尺寸/温度/厚度规格规则
# ── 自动生成: 温度+尺寸 ──

m = re.search(r'(\d+)℃\s*(\d+)×(\d+)', s)
if m:
    result['temperature'] = m.group(1) + '℃'
    result['width'] = m.group(2)
    result['length'] = m.group(3)

# ── 自动生成: 单尺寸 ──

m = re.search(r'^(\d+)×(\d+)$', s.strip())
if m:
    result['width'] = m.group(1)
    result['length'] = m.group(2)

# ── 自动生成: 带括号尺寸 ──

m = re.search(r'(\d+)×\((\d+\+\d+)\)', s)
if m:
    result['width'] = m.group(1)
    result['length_range'] = m.group(2)

# ── 自动生成: 厚度符号 ──

m = re.search(r'δ=(\d+(?:\.\d+)?)', s)
if m:
    result['thickness'] = m.group(1)

# ── 自动生成: 口径符号 ──

m = re.search(r'Φ(\d+(?:\.\d+)?)', s)
if m:
    result['diameter'] = 'Φ' + m.group(1)

# ── 自动生成: DN回路数 ──

m = re.search(r'DN(\d+)[（(](\d+)[）)]\s*(\d+)回路', s)
if m:
    result['diameter'] = 'DN' + m.group(1)
    result['cores'] = m.group(3)
# parse_spec/rules/radiator.py - 散热器/暖气片/浴缸规格规则
# ── 自动生成: 光排管三尺寸 ──

m = re.search(r'(\d+)\*(\d+)\*(\d+)', s)
if m:
    result['diameter'] = m.group(1)
    result['length'] = m.group(2)
    result['thickness'] = m.group(3)

# ── 自动生成: 长度前缀 ──

m = re.search(r'长度(\d+)', s)
if m:
    result['length'] = m.group(1)

# ── 自动生成: 柱型高度 ──

m = re.search(r'(双柱|四柱\d+型)\s+H=(\d+)', s)
if m:
    result['form'] = m.group(1)
    result['height'] = m.group(2)

# ── 自动生成: 盆安装形式 ──

for kw in ['台上盆', '台下盆', '立柱盆']:
    if kw in s:
        result['form'] = kw
        break

# ── 自动生成: 便器出水形式 ──

for kw in ['下出水', '后进后出', '后进水地排水']:
    if kw in s:
        result['installation_type'] = kw
        break
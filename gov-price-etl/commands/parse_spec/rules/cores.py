
# ── 自动生成: 控制电缆芯数 2 ──
m = re.search(r'-(\d+)×', s)
if m:
    result['cores'] = m.group(1)

# ── 自动生成: 电缆芯数 3 ──
m = re.search(r'-(\d+)×', s)
if m:
    result['cores'] = m.group(1)

# ── 自动生成: 电缆芯数 3 ──
m = re.search(r'-(\d+)×', s)
if m:
    result['cores'] = m.group(1)

# ── 自动生成: 计算机电缆对数 3对（每对2芯） ──
m = re.search(r'(\d+)×2×', s)
if m:
    result['cores'] = m.group(1)

# ── 自动生成: 电缆芯数 5 ──
m = re.search(r'-(\d+)×', s)
if m:
    result['cores'] = m.group(1)

# ── 自动生成: 主芯数 3 ──
m = re.search(r'^(\d+)×\d+\+', s)
if m:
    result['cores'] = m.group(1)

# ── 自动生成: 主芯数 3 ──
m = re.search(r'^(\d+)×\d+\+', s)
if m:
    result['cores'] = m.group(1)"

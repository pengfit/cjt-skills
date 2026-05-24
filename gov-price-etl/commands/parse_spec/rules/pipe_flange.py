# parse_spec/rules/pipe_flange.py - 管道/法兰/阀门类规格规则
# ── 自动生成: PN/DN口径+压力 ──

m = re.search(r'PN(\d+(?:\.\d+)?)\s*DN(\d+)', s)
if m:
    result['pressure'] = 'PN' + m.group(1)
    result['diameter'] = 'DN' + m.group(2)

# ── 自动生成: DN+等级 ──

m = re.search(r'DN(\d+)\s+([A-C]级)', s)
if m:
    result['diameter'] = 'DN' + m.group(1)
    result['grade'] = m.group(2)

# ── 自动生成: 型号DN口径 ──

m = re.search(r'(LXSC|LXLC|LXLGR-G2|LXS-E/C|LXS|RLB)\s*DN(\d+)', s)
if m:
    result['diameter'] = 'DN' + m.group(2)

# ── 自动生成: GS宽长 ──

m = re.search(r'GS\s+(\d+)\*(\d+)', s)
if m:
    result['width'] = m.group(1)
    result['length'] = m.group(2)

# ── 自动生成: LXLC-DN口径 ──

m = re.search(r'(LXLC-[^ ]+)\s*DN(\d+)', s)
if m:
    result['diameter'] = 'DN' + m.group(2)
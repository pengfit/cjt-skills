# diameter.py - 管径规则

# ── 自动生成: DN管径 DN150 ──
m = re.search(r'^DN(\d+)$', s)
if m:
    result['diameter'] = 'DN' + m.group(1)

# ── 自动生成: DN管径范围 DN15~50 ──
m = re.search(r'^DN(\d+)~(\d+)$', s)
if m:
    result['diameter'] = 'DN' + m.group(1) + '~' + m.group(2)

# ── 自动生成: DN管径+压力等级 PN1.6 DN100 ──
m = re.search(r'^PN[\d.]+\s+DN(\d+)$', s)
if m:
    result['diameter'] = 'DN' + m.group(1)

# ── 自动生成: D外径×壁厚 (无缝/螺旋钢管) D720×8 → diameter:D720, wall_thickness:8mm ──
m = re.search(r'^D(\d+)\s*[×*]\s*(\d+(?:\.\d+)?)$', s)
if m:
    result['diameter'] = 'D' + m.group(1)
    result['wall_thickness'] = m.group(2) + 'mm'

# ── 自动生成: D外径以内 ──
m = re.search(r'^D(\d+)以内$', s)
if m:
    result['diameter'] = '≤D' + m.group(1)

# ── 自动生成: De管径 ──
m = re.search(r'^De(\d+)$', s)
if m:
    result['diameter'] = 'De' + m.group(1)

# ── 自动生成: Φ管径 (单纯) Φ360 ──
m = re.search(r'^Φ(\d+)$', s)
if m:
    result['diameter'] = 'Φ' + m.group(1)

# ── 自动生成: Φ外径×壁厚 Φ160×10 → diameter:Φ160, wall_thickness:10mm ──
m = re.search(r'^Φ(\d+)\s*[×*]\s*(\d+(?:\.\d+)?)$', s)
if m:
    result['diameter'] = 'Φ' + m.group(1)
    result['wall_thickness'] = m.group(2) + 'mm'

# ── 自动生成: Φ外径范围 Φ3~6 ──
m = re.search(r'^Φ(\d+)\s*~\s*(\d+)$', s)
if m:
    result['diameter'] = 'Φ' + m.group(1) + '~' + m.group(2)

# ── 自动生成: Φ 75mm (带空格) ──
m = re.search(r'^Φ\s*(\d+)mm?$', s)
if m:
    result['diameter'] = 'Φ' + m.group(1)

# ── 自动生成: PN压力等级 (带管径前缀) ──
m = re.search(r'^PN([\d.]+)\s+', s)
if m:
    result['pressure'] = 'PN' + m.group(1)

# ── 自动生成: 阀门型号 DN (J/Z/Q/GL/RLB 等) ──
m = re.search(r'^(?:Z\d+|J\d+|Q\d+|GL\d+|D\d+|B\d+|RLB)\s+.*?\s+DN(\d+)', s)
if m:
    result['diameter'] = 'DN' + m.group(1)

# ── 自动生成: JLBA DN80 单纯 DN ──
m = re.search(r'^(?:JLBA|RLB|GL)\s+DN(\d+)', s)
if m:
    result['diameter'] = 'DN' + m.group(1)

# ── 自动生成: 单纯 DN + 环刚度 DN600 环刚度≥SN12.5 ──
m = re.search(r'^DN(\d+)\s+环刚度', s)
if m:
    result['diameter'] = 'DN' + m.group(1)

# ── 自动生成: LXS DN25 水表 ──
m = re.search(r'^(?:LXS|LXSC|JLBA)\s+.*?\s+DN(\d+)', s)
if m:
    result['diameter'] = 'DN' + m.group(1)

# ── 自动生成: DN20 A级 (品名后缀) ──
m = re.search(r'^DN(\d+)\s+[A-Z]级', s)
if m:
    result['diameter'] = 'DN' + m.group(1)

# ── 自动生成: 压力等级+外径 PN1.6 D110×7.0 ──
m = re.search(r'^PN([\d.]+)\s+D(\d+)', s)
if m:
    result['pressure'] = 'PN' + m.group(1)
    result['diameter'] = 'D' + m.group(2)

# ── 自动生成: 阀门型号 (不带 DN) ──
m = re.search(r'^(?:Z\d+|J\d+|Q\d+|HH\d+|H4[45])\s*[-\w]*\s*(?:DN)?(\d+)', s)
if m:
    result['diameter'] = 'DN' + m.group(1)

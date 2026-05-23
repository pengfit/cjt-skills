# grade.py - 钢材牌号/等级规则
# 核心原则：规则只产生 0 个或 1 个 group，用 result[] 语义赋值
# 0 groups → multi-group handler assigns result[attr] = m.group(0)  ← 之前漏了 else
# 1 group  → result[attr] = groups[0]

# ── 自动生成: 角钢 ∠30×20mm~63×40mm Q235B 范围式 ──
# ∠63*6mm~100*10mm Q235B → width:63~100mm, wall_thickness:6~10mm, grade:Q235B
# 使用 [*×x] 兼容 clean_spec 转换后的 * 符号
m = re.search(r'^∠(\d+)\s*[\*\-\u00d7x]\s*(\d+(?:\.\d+)?)\s*mm\s*[~\-]\s*(\d+)\s*[\*\-\u00d7x]\s*(\d+(?:\.\d+)?)\s*mm', s)
if m:
    result['width'] = m.group(1) + '~' + m.group(3) + 'mm'
    result['wall_thickness'] = m.group(2) + '~' + m.group(4) + 'mm'
    g = re.search(r'Q23[45][A-Z]', s)
    if g:
        result['grade'] = g.group(0)

# ── 自动生成: 角钢简化 ∠40*4 / ∠50*5*5000mm ──
# ∠40*4 → width:40mm, wall_thickness:4mm (无范围，mm后缀可选)
# ∠50*5*5000mm → width:50mm, wall_thickness:5mm, length:5000mm
m = re.search(r'^∠(\d+)\s*[\*\-\u00d7x]\s*(\d+(?:\.\d+)?)(?:\s*mm)?(?:\s*[\*\-×x]\s*(\d+)\s*mm)?$', s)
if m:
    result['width'] = m.group(1) + 'mm'
    result['wall_thickness'] = m.group(2) + 'mm'
    if m.group(3):
        result['length'] = m.group(3) + 'mm'

# ── 自动生成: H型钢 HN100*200*5.5*8 ──
# H型钢类型：H型钢HN100*200*5.5*8 → type:HN, height:100, width:200, web:5.5, flange:8
m = re.search(r'^H型钢\s*(HN|HW|HM)(\d+)\s*[\*\-\u00d7x]\s*(\d+)\s*[\*\-\u00d7x]\s*(\d+(?:\.\d+)?)\s*[\*\-\u00d7x]\s*(\d+(?:\.\d+)?)', s)
if m:
    result['type'] = m.group(1)
    result['height'] = m.group(2) + 'mm'
    result['width'] = m.group(3) + 'mm'
    result['web_thickness'] = m.group(4) + 'mm'
    result['flange_thickness'] = m.group(5) + 'mm'

# ── 自动生成: Q235/Q345 单纯牌号 ──
m = re.search(r'^Q23[45]\s*$', s)
if m:
    result['grade'] = m.group(0)

# ── 自动生成: Q235/Q345 带Φ规格 ──
m = re.search(r'^Q23[45]\s+Φ(\d+(?:\.\d+)?)\s*~\s*(\d+(?:\.\d+)?)', s)
if m:
    result['grade'] = m.group(0).split()[0]
    result['diameter'] = 'Φ' + m.group(1) + '~' + m.group(2)

# ── 自动生成: Q235B 400×3mm (牌号+尺寸) ──
m = re.search(r'^(Q23[345][A-Z]?)\s+(\d+)×(\d+)mm', s)
if m:
    result['grade'] = m.group(1)

# ── 自动生成: 槽钢号数 22~36# ──
m = re.search(r'^(\d+)\s*~\s*(\d+)\s*#', s)
if m:
    result['grade'] = 'Q235'
    result['size_range'] = m.group(1) + '~' + m.group(2) + '#'

# ── 自动生成: HRB400/HPB300 钢筋范围 ──
m = re.search(r'^(HRB\d*)\s+Φ(\d+(?:\.\d+)?)\s*~\s*(\d+(?:\.\d+)?)', s, re.IGNORECASE)
if m:
    result['grade'] = m.group(1).upper()
    result['diameter'] = 'Φ' + m.group(2) + '~' + m.group(3)

# ── 自动生成: HRB400 Φ6 单纯 ──
m = re.search(r'^(HRB\d*)\s+Φ?(\d+)\s*$', s, re.IGNORECASE)
if m:
    result['grade'] = m.group(1).upper()
    result['diameter'] = 'Φ' + m.group(2)

# ── 自动生成: HPB300 Φ8 单纯 ──
m = re.search(r'^(HPB\d*)\s+Φ(\d+)\s*$', s, re.IGNORECASE)
if m:
    result['grade'] = m.group(1).upper()
    result['diameter'] = 'Φ' + m.group(2)

# ── 自动生成: HPB300 Φ6~8 范围 ──
m = re.search(r'^(HPB\d*)\s+Φ(\d+(?:\.\d+)?)\s*~\s*(\d+(?:\.\d+)?)', s, re.IGNORECASE)
if m:
    result['grade'] = m.group(1).upper()
    result['diameter'] = 'Φ' + m.group(2) + '~' + m.group(3)

# ── 自动生成: H型钢 H100~H250 Q235B ──
m = re.search(r'^(H\d+)\s*~\s*(H?\d+)\s+Q23[45][A-Z]?', s, re.IGNORECASE)
if m:
    result['grade'] = 'Q235B'
    result['height_range'] = m.group(1) + '~' + m.group(2)

# ── 自动生成: 防火门等级 甲级/乙级/丙级 ──
m = re.search(r'^(甲|乙|丙)级$', s)
if m:
    result['grade'] = m.group(0)

# ── 自动生成: 水泥 P.O42.5R ──
m = re.search(r'P\.O\d+\.?\d*R?', s)
if m:
    result['grade'] = m.group(0)

# ── 自动生成: 水泥 P.S.A42.5 ──
m = re.search(r'P\.S\.A\d+\.?\d*', s)
if m:
    result['grade'] = m.group(0)

# ── 自动生成: 水泥 P.C32.5 / P.C42.5 ──
m = re.search(r'P\.C\.\d+\.?\d*R?', s)
if m:
    result['grade'] = m.group(0)

# ── 自动生成: 混凝土 C30 P10 强度+抗渗 ──
m = re.search(r'^C(\d+)\s+P(\d+)$', s)
if m:
    result['grade'] = 'C' + m.group(1)
    result['pressure_class'] = 'P' + m.group(2)

# ── 自动生成: 混凝土 C30 单纯 ──
m = re.search(r'^C(\d+)$', s)
if m:
    result['grade'] = 'C' + m.group(1)

# ── 自动生成: 沥青混凝土 AC-25 SBS AC-10 ──
m = re.search(r'^(?:SBS\s*)?AC-\d+', s, re.IGNORECASE)
if m:
    result['grade'] = m.group(0).upper()

# ── 自动生成: 砂浆 DM M10 DS M20 ──
m = re.search(r'^(D[MS])\s+M(\d+)', s, re.IGNORECASE)
if m:
    result['grade'] = m.group(1).upper() + ' M' + m.group(2)

# ── 自动生成: Q235B/Q345B 带后缀牌号（通用，排在最后） ──
m = re.search(r'Q23[45][A-Z]', s)
if m:
    result['grade'] = m.group(0)

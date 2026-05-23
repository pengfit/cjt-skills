# wall_thickness.py - 壁厚/板厚规则

# ── 自动生成: δ板厚范围 δ12~16 ──
m = re.search(r'^δ(\d+(?:\.\d+)?)\s*~\s*(\d+(?:\.\d+)?)(?:\s+|$)', s)
if m:
    result['wall_thickness'] = m.group(1) + '~' + m.group(2) + 'mm'

# ── 自动生成: δ单值板厚 δ2~4 (无空格解释为范围) ──
m = re.search(r'^δ(\d+(?:\.\d+)?)\s*~\s*(\d+)$', s)
if m:
    result['wall_thickness'] = m.group(1) + '~' + m.group(2) + 'mm'

# ── 自动生成: δ单值板厚(带空格) δ2.5~5 SS304 ──
m = re.search(r'^δ(\d+(?:\.\d+)?)\s*~\s*(\d+(?:\.\d+)?)\s+', s)
if m:
    result['wall_thickness'] = m.group(1) + '~' + m.group(2) + 'mm'

# ── 自动生成: 厚:数字mm 厚度:数字mm ──
m = re.search(r'^(?:厚度?|厚)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*mm', s, re.IGNORECASE)
if m:
    result['wall_thickness'] = m.group(1) + 'mm'

# ── 自动生成: 厚数字mm (无冒号) ──
m = re.search(r'^厚(\d+(?:\.\d+)?)\s*mm', s, re.IGNORECASE)
if m:
    result['wall_thickness'] = m.group(1) + 'mm'

# ── 自动生成: 板材厚度mm 12mm (纯数字+mm) ──
m = re.search(r'^(\d+(?:\.\d+)?)\s*mm$', s)
if m and not re.search(r'[××xX]', s):
    result['wall_thickness'] = m.group(1) + 'mm'

# ── 自动生成: 井盖承压等级 承压等级C250 ──
m = re.search(r'承压等级\s*[AC](\d+)', s)
if m:
    result['pressure_class'] = 'C' + m.group(1)
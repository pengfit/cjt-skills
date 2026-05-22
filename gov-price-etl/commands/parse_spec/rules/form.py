# 角钢 ∠63*6mm~100*10mmQ235B
m = re.search(r'∠(\d+)\*(\d+)mm~(?:(\d+)\*(\d+)mm)?(Q\d+(?:B)?)?', s)
if m:
    result['type'] = '∠'
    result['spec1'] = m.group(1)
    result['thickness'] = m.group(2) + 'mm'
    if m.group(3):
        result['spec2'] = m.group(3)
    if m.group(4):
        result['thickness2'] = m.group(4) + 'mm'
    if m.group(5):
        result['grade'] = m.group(5)

# 角钢格式: ∠边长*厚度mm~边长*厚度mm
m = re.search(r'∠(\d+)\*(\d+(?:\.\d+)?)\s*mm', s)
if m:
    result['form'] = '角钢'
    result['angle_size'] = m.group(1)
    result['thickness'] = m.group(2) + 'mm'
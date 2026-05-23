# material.py - 材质规则

# ── 自动生成: 不锈钢材质 SS304 SS316 ──
m = re.search(r'SS\d{3}', s, re.IGNORECASE)
if m:
    result['material'] = m.group(0)

# ── 自动生成: 铝合金材质 ──
m = re.search(r'铝合金', s)
if m:
    result['material'] = '铝合金'

# ── 自动生成: 不锈钢板材质 ──
m = re.search(r'不锈钢板?|不绣钢', s)
if m:
    result['material'] = '不锈钢'

# ── 自动生成: PVC/PPR/PE 材质 ──
m = re.search(r'\b(PVC|PPR|PE|PB|PP|铸铁|钢|铜|镀锌)\b', s, re.IGNORECASE)
if m:
    result['material'] = m.group(1).upper()

# ── 自动生成: 提取阀门型号 ──
m = re.search(r'^(ZSFZ)', s)
if m:
    result['series'] = m.group(1)

# ── 自动生成: 提取系列型号 ──
m = re.search(r'(760型|660型|500型)', s)
if m:
    result['series'] = m.group(1)

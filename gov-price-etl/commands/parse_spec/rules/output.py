
# ── 自动生成: EPS输出容量 45kVA ──
m = re.search(r'(\d+(?:\.\d+)?)\s*(?:kVA|KVA)', s)
if m:
    result['output'] = m.group(1) + 'kVA'

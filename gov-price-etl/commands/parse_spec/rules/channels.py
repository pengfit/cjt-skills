
# ── 自动生成: 12口表示光纤配线架容量为12口 ──
m = re.search(r'(\d+)口', s)
if m:
    result['channels'] = m.group(1)

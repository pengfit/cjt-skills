
# ── 自动生成: 3回路表示芯数/回路数量 ──
m = re.search(r'(\d+)回路', s)
if m:
    result['cores'] = m.group(1)

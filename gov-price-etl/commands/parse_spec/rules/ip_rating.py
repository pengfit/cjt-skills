
# ── 自动生成: 提取防护等级 ──
m = re.search(r'(IP\d+)', s)
if m:
    result['ip_rating'] = m.group(1)


# ── 自动生成: 70℃ 表示阀门公称动作温度为70摄氏度 ──
m = re.search(r'(\d+)℃', s)
if m:
    result['temperature'] = m.group(1) + '℃'

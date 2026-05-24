
# ── 自动生成: 综合各色表示颜色为综合/各色（多色可选） ──
m = re.search(r'(综合各色|各色|单色|白色|黑色|灰色)', s)
if m:
    result['color'] = m.group(1)

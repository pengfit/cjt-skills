
# ── 自动生成: 提取安装形式台上盆 ──
m = re.search(r'^(台上盆|台下盆|嵌入式|挂墙式)', s)
if m:
    result['installation_type'] = m.group(1)


# ── 自动生成: 台上盆表示洗脸盆安装形式为台上式（台下盆安装于台面下方） ──
m = re.search(r'(台上盆|台下盆|台下式|挂盆|立柱盆|艺术盆|半嵌盆)', s)
if m:
    result['installation_type'] = m.group(1)

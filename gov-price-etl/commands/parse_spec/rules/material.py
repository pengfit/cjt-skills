
# ── 自动生成: 交联聚乙烯绝缘铜芯电缆 YJV ──
m = re.search(r'^(YJV|YJLV|YJY|YJLY)', s)
if m:
    result['material'] = m.group(1)

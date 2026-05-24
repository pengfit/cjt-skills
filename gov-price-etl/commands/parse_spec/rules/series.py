
# ── 自动生成: 低烟无卤阻燃 WDZ ──
m = re.search(r'(WDZ|WDZAN)', s)
if m:
    result['series'] = 'WDZ'

# ── 自动生成: 低烟无卤阻燃 WDZ ──
m = re.search(r'(WDZ|WDZAN)', s) if m:     result['series'] = 'WDZ'

# ── 自动生成: 低烟无卤阻燃耐火 WDZN ──
m = re.search(r'(WDZN)', s)
if m:
    result['series'] = 'WDZN'

# ── 自动生成: 低烟无卤阻燃 WDZ ──
m = re.search(r'(WDZ|WDZAN)', s) if m:     result['series'] = 'WDZ'

# ── 自动生成: 计算机屏蔽电缆系列 DJYVP ──
m = re.search(r'(DJYVP|DJYV|DJV)', s)
if m:
    result['series'] = m.group(1)

# ── 自动生成: 低烟无卤阻燃 WDZ ──
m = re.search(r'(WDZ|WDZAN)', s)
if m:
    result['series'] = 'WDZ'

# ── 自动生成: 交联聚乙烯绝缘铜芯电缆系列 YJV ──
m = re.search(r'^(YJV|YJLV|YJY|YJLY)', s)
if m:
    result['series'] = m.group(1)"

# ── 自动生成: test ──
m = re.search(r'(WDZN|WDZAN|ZN)', s)\nif m:\n    result['series'] = m.group(1)

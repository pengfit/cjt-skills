
# ── 自动生成: 贮压悬挂式表示灭火装置安装形式 ──
m = re.search(r'(贮压式|贮压悬挂式|悬挂式|推车式|手提式)', s)
if m:
    result['form'] = m.group(1)

# ── 自动生成: 干接点型表示开关触点类型为干接点（无源触点） ──
m = re.search(r'(干接点型|湿接点型|常开型|常闭型|转换型|单极型|双极型)', s)
if m:
    result['form'] = m.group(1)

# ── 自动生成: LC接口表示光模块接口类型为LC ──
m = re.search(r'(LC接口|SC接口|FC接口|ST接口|MPO接口)', s)
if m:
    result['form'] = m.group(1)

# ── 自动生成: 抗微生物型表示产品功能类型 ──
m = re.search(r'(抗微生物型|抗菌型|防霉型|净化型|自洁型)', s)
if m:
    result['form'] = m.group(1)

# ── 自动生成: 块状表示产品形态为块状 ──
m = re.search(r'(块状|粒状|粉状|液态|气态|膏状|固态)', s)
if m:
    result['form'] = m.group(1)

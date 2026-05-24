
# ── 自动生成: MVD 为密闭型电动风量调节阀系列型号 ──
m = re.search(r'(MVD|MVF|MVC|MVJ|MVT|MVZ)', s)
if m:
    result['series'] = m.group(1)

# ── 自动生成: FZX-ACT3~5/1.2 为超细干粉装置完整型号 ──
m = re.search(r'(FZX-[A-Z]+[\w]*\d+(?:~\d+)?(?:/\d+(?:\.\d+)?)?)', s)
if m:
    result['series'] = m.group(1)

# ── 自动生成: SS 为室外地上消防栓型号前缀 ──
m = re.search(r'^([A-Z]{2})\d+-\d+(?:\.\d+)?', s)
if m:
    result['series'] = m.group(1)

# ── 自动生成: 六类模块表示网络模块级别为六类（Cat6） ──
m = re.search(r'(六类|超五类|五类|超六类|七类|八类)', s)
if m:
    result['series'] = m.group(1)

# ── 自动生成: 万兆表示传输速率为万兆（10Gbps） ──
m = re.search(r'(万兆|千兆|百兆|10G|1G|100M)', s)
if m:
    result['series'] = m.group(1)

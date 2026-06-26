"""陕西省工程造价 PDF 解析器。

支持的页面类型（按检测顺序）：
  A: 多县区表（除税价 + 含税价 各一行，每行 N 个 county 价格）—— 安康
  D: 多县区表（仅除税价一行，每行 N 个 county 价格）—— 汉中
  E: 多县区表（county 成组，每组 2 个价格）—— 咸阳 last section
  B: 单价表（编码+名称+规格型号+单位+除税价格+含税价格，6 列）—— 咸阳 / 渭南 / 陕西province
  C: 单价表（含税+除税+税率，7 列，列顺序与 B 不同）—— 铜川

未识别的页面（如工人工资、安装工程、租赁）会被跳过。
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import pypdf


# ─── 通用工具 ────────────────────────────────────────────────────────────────
def _parse_number(s):
    """提取浮点数（容忍中文逗号、空格）"""
    if s is None:
        return None
    s = str(s).strip()
    if not s or s in ('/', '-', '—'):
        return None
    s = s.replace(',', '').replace(' ', '').replace('元', '')
    try:
        v = float(s)
        return v if v >= 0 else None
    except ValueError:
        return None


def _line_ends_with_prices(line):
    """判断行末是否以价格结尾（两个或更多数字），用于检测 PDF 换行。"""
    line = line.strip()
    if not line:
        return False
    # 行末 2 个或以上被空白分隔的数字
    m = re.search(r'(\d+\.?\d*)\s+(\d+\.?\d*)\s*$', line)
    return bool(m)


def _line_ends_with_price(line):
    """行末以 1 个数字结尾（可能后面是备注等）。"""
    line = line.strip()
    return bool(re.search(r'\d+\.?\d*\s*$', line) and not re.search(r'[a-zA-Z\u4e00-\u9fff]\s*$', line))


def _is_boundary_line(line):
    r"""判断是否为逻辑行边界（不应与后续行合并）。

    边界类型：
      - 纯代码行（^\d{6,9}$）：表示材料代码独立成行，是新材料的开始
      - 代码 + 其余内容（^\d{6,9}\s+\S）：完整材料行
      - 类目行（^\d{2}\s+中文）
      - 县/区 header、表中标记（除税价/含税价/价格信息/价格（元））
      - 表头（编码 + 名称）
      - 县域名称（纯中文、无数字）
      - 纯价格行（全是被空白分隔的数字）
      - 纯页脚/页码
    """
    line = line.strip()
    if not line:
        return True
    # 纯代码行（只有 digits） → 视为边界（新材料的开始）
    if re.match(r'^\d{6,9}$', line):
        return True
    # 代码 + 其余内容（如 “010101303 热轧光圆钢筋”） → 仅当以价格结尾才是边界
    # 否则继续 join 下一行（例：code 后面 spec 被换行拆开）
    if re.match(r'^\d{6,9}\s+\S', line):
        if re.search(r'\d+\.?\d*\s+\d+\.?\d*\s*$', line):
            return True
        return False
    if re.match(r'^\d{2}\s+[\u4e00-\u9fff]', line):
        return True
    if re.match(r'^编码\s', line) or '材料名称' in line:
        return True
    if line.startswith('除税价') or line.startswith('含税价') or '除税价格' in line:
        return True
    if line == '示范区' or '县区' in line or '各县' in line:
        return True
    # 汉中县名（短名）
    hz_names = {'南郑', '城固', '洋县', '佛坪', '西乡', '镇巴', '留坝', '勉县', '略阳', '宁强'}
    if line in hz_names:
        return True
    # 纯价格行（>=3 个被空白分隔的数字）
    tokens = line.split()
    if len(tokens) >= 3:
        num_count = sum(1 for t in tokens if re.match(r'^\d+\.?\d*$', t))
        if num_count >= len(tokens) * 0.8:
            return True
    # 页码
    if re.match(r'^[\d·.\-\s]+$', line):
        return True
    return False


def _join_wrapped_lines(lines):
    """合并被 PDF 换行拆开的逻辑行。
    
    启发：上一行不以价格结尾 且 不是边界行，且下一行不是新边界行，则合并。
    """
    out = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        # 边界行：单独成行
        if _is_boundary_line(line):
            out.append(line)
            i += 1
            continue
        # 检查是否需要向后合并
        joined = line
        while i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if not next_line:
                i += 1
                continue
            if _is_boundary_line(next_line):
                break
            # 当前行不以 2 个价格结尾才合并
            if _line_ends_with_prices(joined) or _line_ends_with_single_price(joined):
                break
            joined = joined + ' ' + next_line
            i += 1
        out.append(joined)
        i += 1
    return out


def _line_ends_with_single_price(line):
    """行末以单个数字结尾（合理结尾，如一个 price + 备注）。"""
    line = line.strip()
    # 必须是 行末正好 1 个数字，且前面有 unit
    return bool(re.search(r'(?:t|T|m|㎡|m2|m3|m³|m²|个|只|块|张|套|把|片|根|箱|袋|桶|卷|本|册|组|份|座|盏|台|辆|樘|件|米|千米|Km|km|天|月|年|次|工日|元|千块|千克|kg|Kg|KG|台班|天|月)\s+\d+\.?\d*\s*$', line))


# ─── 县城/区识别 ─────────────────────────────────────────────────────────────
# 关键字结尾 + 黑名单
_COUNTY_END = ('区', '县', '市', '示范区')
_COUNTY_BLOCKLIST = {
    '编码', '材料编码', '名称', '材料名称', '规格', '规格型号', '规格及型号',
    '型号', '单位', '类别', '单价', '除税价格', '含税价格', '税率',
    '备注', '元', '以下材料税率', '以下税率', '到工地价', '示范区',
    '市场价', '信息价', '指导价', '厂商报价', '生产销售企业报价',
    '价格', '价格信息', '价格(元)', '材料', '项目编码', '项目名称',
    '工程量计算规则', '计量单位', '人工单价', '工种', '日工资',
}


def _is_county_token(tok):
    """判断是否为县/区/市名 token"""
    tok = tok.strip()
    if not tok or len(tok) > 8:
        return False
    if tok in _COUNTY_BLOCKLIST:
        return False
    # 单独“示范区”不算 county，但“恒口示范区”算
    if tok == '示范区':
        return False
    if any(tok.endswith(e) for e in _COUNTY_END):
        return True
    return False


def _extract_counties_from_text(text):
    """从页面文本中提取 counties 列表。
    
    县名通常出现在表头附近。规则：
      - 找含有 ≥ 3 个 county token 的"header"行
      - county tokens 可跨多行（如 "恒口\n示范区"）
    """
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    counties = []
    # 合并相邻行（处理 "汉滨区 汉阴县 ... 恒口\n示范区"）
    for i, line in enumerate(lines[:8]):  # 只看前 8 行（header 区）
        # 先按空格 split
        tokens = []
        for t in re.split(r'\s+', line):
            t = t.strip()
            if not t:
                continue
            # 处理 "恒口" 跟 "示范区" 跨行 → 合并成 "恒口示范区"
            if t == '恒口' and i + 1 < len(lines) and lines[i + 1].startswith('示范区'):
                t = '恒口示范区'
                lines[i + 1] = ''  # 标记为已合并
            tokens.append(t)
        for tok in tokens:
            if _is_county_token(tok) and tok not in counties:
                counties.append(tok)
        if len(counties) >= 3:
            # 已找到足够 county，停止
            break
    return counties


# ─── 页面类型检测 ────────────────────────────────────────────────────────────
def _has_table_marker(text):
    """检测页面是否包含材料价格表头（编码+名称）。"""
    return bool(re.search(r'(?:^|\n)\s*(?:材料编码|编码)\s+(?:材料名称|名称)\s+(?:规格型号|规格及型号|型号规格)', text))


def detect_page_type(text):
    """检测页面类型，返回 (type, header_info)。"""
    # 跳过明显不是材料价格表的页面
    if '日工资' in text or '人工单价' in text:
        return ('skip', None)
    if '工程量计算规则' in text:
        return ('skip', None)
    if '价格信息' in text and len(text) < 200:
        return ('skip', None)
    if '施工仪器仪表' in text and '编码' not in text:
        return ('skip', None)

    # ── 类型 G: 商洛（优先识别，因为商洛 PDF 没有传统表头）───
    if '商洛' in text and '工程造价管理信息' in text and len(text) > 200:
        return ('G', None)

    # 纯目录页（无编码材料行）
    if not _has_table_marker(text) and not re.search(r'^\d{6,9}\s+', text, re.MULTILINE):
        return ('skip', None)

    counties = _extract_counties_from_text(text)
    has_table_header = _has_table_marker(text)

    # ── 类型 A: 多县区表（除税价 + 含税价 两行，county 名带 区/县/市）───
    if counties and has_table_header and '除税价' in text and '含税价' in text:
        return ('A', {'counties': counties})

    # ── 类型 D: 多县区表（仅除税价一行，county 名为短名如 南郑/城固）───
    # 特征：有 县区名（不带 区/县 结尾），且"除税价格"出现，材料价格表头存在
    if counties and has_table_header and ('除税价' in text or '除税价格' in text):
        # 区分 A 和 D：A 有"含税价"，D 没有
        if '含税价' not in text:
            return ('D', {'counties': counties})

    # ── 类型 E: 县城成组（county 成组，每组 2 个价格）───
    if counties and has_table_header and '除税价' in text and '含税价' in text:
        return ('E', {'counties': counties})

    # ── 类型 C: 单价表（含税+除税+税率 7 列，铜川）───
    # 铜川的特征：含税价格 在 除税价格 之前，且有"税率%"列
    if has_table_header and re.search(r'含税价格.*?除税价格', text, re.DOTALL) and ('税率' in text and '%' in text):
        return ('C', None)

    # ── 类型 B: 单价表（6 列，除税价 + 含税价）───
    if has_table_header and '除税价格' in text and '含税价格' in text:
        return ('B', None)

    # ── 类型 F: 汉中县区表（顶材料清单 + 中间 county header + 底价格行）───
    # 特征：含“汉中市各县”或“南郑/城固/洋县” 等汉中县名
    hz_county_names = ['南郑', '城固', '洋县', '佛坪', '西乡', '镇巴', '留坝', '勉县', '略阳', '宁强']
    hz_hits = sum(1 for c in hz_county_names if c in text)
    if hz_hits >= 5 and has_table_header:
        return ('F', None)

    # ── 类型 G: 商洛（pdfplumber layout-aware）—— 已在 detect 开头处理 ──

    return ('skip', None)


# ─── 各类解析器 ──────────────────────────────────────────────────────────────

@dataclass
class MaterialRow:
    code: str
    breed: str
    spec: str
    unit: str
    category: str = ''
    county: str = ''           # 多县区表专用
    price: Optional[float] = None       # 除税价
    tax_price: Optional[float] = None   # 含税价


_UNIT_KEYWORDS = [
    '台班', '张·天', '㎡·天', 'm•天', 'm·天', 'm³·天', 'm2·天',
    '千块', '百元', '千克', 'Km', 'km', 'm³', 'm2', '㎡', 'm',
    '天', '月', '年', '次', '套', '把', '片', '根', '块', '吨', '个',
    'T', 't', 'M', 'm',
]
_UNIT_TOKENS_RE = re.compile(
    r'(t|T|m|㎡|m2|m3|m³|m²|个|只|块|张|套|把|片|根|箱|袋|桶|卷|本|册|组|份|座|盏|台|辆|'
    r'樘|件|块|米|千米|Km|km|天|月|年|次|工日|台班|元|百元|'
    r'千块|千克|kg|Kg|KG|吨|T|m2·天|㎡·天|m·天|m³·天|张·天|'
    r'\d+m|\d+㎡|\d+m³|\d+m2)'
)


def _split_breed_spec_unit(line, code_end):
    """从 material 行（去掉 code 部分）切出 (breed, spec, unit)。
    
    启发：单位通常是最后 1-2 个 token；breed 在 spec 之前。
    """
    rest = line[code_end:].strip()
    if not rest:
        return ('', '', '')

    # 1. 找单位：尝试从末尾往前匹配单位关键字
    # 单位可能是 "m³"、"t"、"千块"、"㎡·天" 等
    m = re.search(
        r'\s+((?:台班|㎡·天|m2·天|m·天|m³·天|张·天|'
        r'千块|百元|千克|kg|Kg|KG|'
        r'm3|m³|m2|㎡|m²|台班|月|天|'
        r't|T|m|个|只|块|张|套|把|片|根|箱|袋|桶|卷|本|册|组|份|座|盏|台|辆|樘|件|米|千米|Km|km|次|工日|元))(?=\s+\d|\s*$)',
        rest
    )
    if m:
        unit = m.group(1).strip()
        breed_spec = rest[:m.start()].strip()
    else:
        unit = ''
        breed_spec = rest

    # 2. 切 breed vs spec：
    # 启发：breed 是开头连续的中文，到第一个数字/英文/特殊字符为止
    # 例如 "热轧光圆钢筋 HPB300 Φ6~8" → breed="热轧光圆钢筋", spec="HPB300 Φ6~8"
    # 例如 "热轧光圆钢筋（高线） HPB300 Φ6~8" → breed="热轧光圆钢筋（高线）", spec="HPB300 Φ6~8"
    # 例如 "砾 石 0.5~1.5cm"（无空格）→ breed="砾 石", spec="0.5~1.5cm"
    bm = re.match(r'^([\u4e00-\u9fff（）()]+?)\s+(\S.*)$', breed_spec)
    if bm:
        breed = bm.group(1).strip()
        spec = bm.group(2).strip()
    else:
        # 兜底：整段当 breed，spec 空
        breed = breed_spec
        spec = ''

    return (breed, spec, unit)


def _parse_code_line(line):
    """解析一行 material 行（如 '010101303 热轧光圆钢筋 HPB300 Φ6~8 t'）。
    
    返回 (code, breed, spec, unit) 或 None。
    """
    m = re.match(r'^(\d{6,9})\s+(.+)$', line)
    if not m:
        return None
    code = m.group(1)
    breed, spec, unit = _split_breed_spec_unit(line, m.end(1))
    return (code, breed, spec, unit)


def _category_line(line):
    """检测是否为类目行（'01  黑色及有色金属'）"""
    m = re.match(r'^\d{2}\s+[\u4e00-\u9fff（）()]+', line)
    return m.group(0).strip() if m else None


def parse_page_type_A(text, counties):
    """类型 A: 多县区表（除税价 + 含税价 两行）。
    
    结构：
      [可选 category 行] '01 黑色及有色金属'
      [county header] '编码 材料名称 规格及型号 单位 类别 汉滨区 ... 紫阳县 恒口'
      [county header 续] '示范区'
      [material 行] '010101303 热轧光圆钢筋 高线HPB300,Φ6-Φ8 t'
      [price 行 1] '除税价 3371.68 3389.38 ...'
      [price 行 2] '含税价 3810.00 3830.00 ...'
    """
    rows = []
    raw_lines = [l.strip() for l in text.split('\n') if l.strip()]
    lines = _join_wrapped_lines(raw_lines)
    i = 0
    n = len(counties)
    cur_category = ''

    while i < len(lines):
        line = lines[i]
        cat = _category_line(line)
        if cat:
            cur_category = cat
            i += 1
            continue

        # 跳过表头（编码 材料名称 ...）
        if re.match(r'^(编码|材料编码)\s', line) or re.match(r'^汉中市|^咸阳市|^安康市', line):
            i += 1
            continue
        if '单位' in line and ('除税' in line or '含税' in line or len(line) < 50):
            i += 1
            continue

        # 解析 material 行
        parsed = _parse_code_line(line)
        if not parsed:
            i += 1
            continue
        code, breed, spec, unit = parsed

        # 下一行应是"除税价..."
        if i + 2 >= len(lines) or '除税价' not in lines[i + 1] or '含税价' not in lines[i + 2]:
            i += 1
            continue

        no_tax_prices = re.findall(r'\d+\.?\d*', lines[i + 1].replace('除税价', ''))
        tax_prices = re.findall(r'\d+\.?\d*', lines[i + 2].replace('含税价', ''))

        # 数量对齐
        if len(no_tax_prices) >= n:
            no_tax_prices = no_tax_prices[:n]
        else:
            # 缺失：补 None
            no_tax_prices += [None] * (n - len(no_tax_prices))
        if len(tax_prices) >= n:
            tax_prices = tax_prices[:n]
        else:
            tax_prices += [None] * (n - len(tax_prices))

        for k, county in enumerate(counties):
            rows.append(MaterialRow(
                code=code, breed=breed, spec=spec, unit=unit,
                category=cur_category, county=county,
                price=_parse_number(no_tax_prices[k]),
                tax_price=_parse_number(tax_prices[k]),
            ))
        i += 3
    return rows


def parse_page_type_D(text, counties):
    """类型 D: 多县区表（仅除税价一行）。
    
    结构：
      [material 行] '010101303 热轧光圆钢筋（高线） HPB300 Φ6~8 t'
      [price 行]    '除税价（或除税价格） 3354.00 3334.00 ...'
    """
    rows = []
    raw_lines = [l.strip() for l in text.split('\n') if l.strip()]
    lines = _join_wrapped_lines(raw_lines)
    n = len(counties)
    i = 0
    cur_category = ''

    while i < len(lines):
        line = lines[i]
        cat = _category_line(line)
        if cat:
            cur_category = cat
            i += 1
            continue
        if re.match(r'^(编码|材料编码)\s', line):
            i += 1
            continue
        if '汉中市' in line or '除税价格' in line and '单位' in line:
            i += 1
            continue

        parsed = _parse_code_line(line)
        if not parsed:
            i += 1
            continue
        code, breed, spec, unit = parsed

        # 下一行应是除税价格行（不一定含 "除税价" 标记，因为 header 单独一页）
        if i + 1 >= len(lines):
            i += 1
            continue
        next_line = lines[i + 1]
        if '除税价' in next_line or '除税价格' in next_line:
            price_str = re.sub(r'^(除税价|除税价格|（元）|（除税价）)\s*', '', next_line)
            prices = re.findall(r'\d+\.?\d*', price_str)
        else:
            # 可能是空格分开的多个数字
            tokens = next_line.split()
            prices = [t for t in tokens if re.match(r'^\d+\.?\d*$', t)]
        if len(prices) >= n:
            prices = prices[:n]
        else:
            prices += [None] * (n - len(prices))

        for k, county in enumerate(counties):
            rows.append(MaterialRow(
                code=code, breed=breed, spec=spec, unit=unit,
                category=cur_category, county=county,
                price=_parse_number(prices[k]),
                tax_price=None,
            ))
        i += 2
    return rows


def parse_page_type_E(text, counties):
    """类型 E: 县城成组（每 county 2 个价格：除税+含税）。
    
    结构：
      [material 行] '040103901 钢材运费 t'
      [price 行]    '除税价 含税价 除税价 含税价 ...' （N counties × 2 = 2N 个数字）
    """
    rows = []
    raw_lines = [l.strip() for l in text.split('\n') if l.strip()]
    lines = _join_wrapped_lines(raw_lines)
    n = len(counties)
    i = 0
    cur_category = ''

    while i < len(lines):
        line = lines[i]
        cat = _category_line(line)
        if cat:
            cur_category = cat
            i += 1
            continue
        if re.match(r'^(编码|材料编码)\s', line):
            i += 1
            continue
        if '咸阳' in line and len(line) < 60:
            i += 1
            continue

        parsed = _parse_code_line(line)
        if not parsed:
            i += 1
            continue
        code, breed, spec, unit = parsed

        if i + 1 >= len(lines):
            i += 1
            continue
        next_line = lines[i + 1]
        # E 类型的 price 行可能在一行或两行（"除税价 含税价" 多个 county）
        if not re.search(r'\d', next_line):
            i += 1
            continue

        # 抓取所有数字
        prices = re.findall(r'\d+\.?\d*', next_line)
        # 期望 2N 个
        if len(prices) >= 2 * n:
            prices = prices[:2 * n]
        else:
            prices += [None] * (2 * n - len(prices))

        for k, county in enumerate(counties):
            no_tax = _parse_number(prices[2 * k])
            with_tax = _parse_number(prices[2 * k + 1])
            rows.append(MaterialRow(
                code=code, breed=breed, spec=spec, unit=unit,
                category=cur_category, county=county,
                price=no_tax, tax_price=with_tax,
            ))
        i += 2
    return rows


def parse_page_type_B(text):
    """类型 B: 单价表 6 列（编码 + 名称 + 规格 + 单位 + 除税价 + 含税价）。
    
    每行一个材料，city = PDF 设区市名 或 "陕西"（省本级）。
    """
    rows = []
    raw_lines = [l.strip() for l in text.split('\n') if l.strip()]
    lines = _join_wrapped_lines(raw_lines)
    cur_category = ''
    for line in lines:
        cat = _category_line(line)
        if cat:
            cur_category = cat
            continue
        if re.match(r'^(材料编码|编码)\s', line):
            continue
        if '材料名称' in line and '规格型号' in line:
            continue

        parsed = _parse_code_line(line)
        if not parsed:
            continue
        code, breed, spec, unit = parsed

        # 找最后两个数字（除税、含税）
        nums = re.findall(r'\d+\.?\d*', line)
        # 滤掉 code 和 unit 中可能的小数字（如 "5mm"）
        # 启发：价格通常 ≥ 0.1，且最右两个
        # 更稳：找最后两个数字（price 一般在行尾）
        if len(nums) >= 2:
            tax_p = _parse_number(nums[-1])
            no_tax = _parse_number(nums[-2])
            if tax_p is not None and no_tax is not None and tax_p >= no_tax:
                rows.append(MaterialRow(
                    code=code, breed=breed, spec=spec, unit=unit,
                    category=cur_category,
                    price=no_tax, tax_price=tax_p,
                ))
                continue
            # 兜底：尝试 -1 和 -3（中间可能是 unit 或 spec 中的数字）
            if len(nums) >= 3:
                no_tax = _parse_number(nums[-3])
                if no_tax is not None:
                    rows.append(MaterialRow(
                        code=code, breed=breed, spec=spec, unit=unit,
                        category=cur_category,
                        price=no_tax, tax_price=tax_p,
                    ))
    return rows


def parse_page_type_C(text):
    """类型 C: 单价表 7 列（含税+除税+税率）。
    
    铜川格式：编码 名称 规格型号 单位 含税价格（元） 除税价格（元） 税率%
    """
    rows = []
    raw_lines = [l.strip() for l in text.split('\n') if l.strip()]
    lines = _join_wrapped_lines(raw_lines)
    cur_category = ''
    for line in lines:
        cat = _category_line(line)
        if cat:
            cur_category = cat
            continue
        if re.match(r'^(编码)\s', line) and '含税' in line:
            continue

        parsed = _parse_code_line(line)
        if not parsed:
            continue
        code, breed, spec, unit = parsed

        nums = re.findall(r'\d+\.?\d*', line)
        # 顺序：含税价格 除税价格 税率%
        if len(nums) >= 3:
            tax_p = _parse_number(nums[-3])
            no_tax = _parse_number(nums[-2])
            if tax_p is not None and no_tax is not None:
                rows.append(MaterialRow(
                    code=code, breed=breed, spec=spec, unit=unit,
                    category=cur_category,
                    price=no_tax, tax_price=tax_p,
                ))
    return rows


def _group_hanzhong_material_blocks(lines, start_idx, end_idx):
    """汉中 PDF 材料块分组：从 start_idx 开始到 end_idx，按 6-9 位 code 拆分。
    
    每块 = code 行 + 后续非 code、非 county、非价格、非装饰行（最多 8 行）。
    返回 [(code, breed_spec_unit_text, line_indices), ...]
    """
    hz_counties_full = ['南郑', '城固', '洋县', '佛坪', '西乡', '镇巴', '留坝', '勉县', '略阳', '宁强']
    hz_decorative = ['编码', '名称', '材料名称', '规格型号', '规格及型号', '单位', '类别', '除税价格', '含税价格', '税率',
                     '以下材料税率', '以下税率', '汉中市各县', '材料信息价', '价格信息', '价 格 信 息', '备注']
    blocks = []
    cur_code = None
    cur_text_lines = []
    cur_start = -1

    def _flush():
        nonlocal cur_code, cur_text_lines, cur_start
        if cur_code is not None:
            text = ' '.join(cur_text_lines).strip()
            # 清理多余空格
            text = re.sub(r'\s+', ' ', text).strip()
            blocks.append((cur_code, text))
        cur_code = None
        cur_text_lines = []
        cur_start = -1

    for i in range(start_idx, end_idx):
        line = lines[i].strip()
        if not line:
            continue
        # 装饰行跳过
        is_decorative = (line in hz_decorative or any(d in line for d in ['编码 名称', '以下材料税率', '汉中市', '价格信息', '联系电话', '联系人']))
        if is_decorative:
            continue
        # county 行跳过
        if line in hz_counties_full:
            continue
        # 纯价格行（被空白分隔的小数，个位 n~10）跳过
        # 例 "3354.00   3334.00    3324.00 ..." — 这种是价格行
        # 例 "HPB300 Φ 6~8" — 这种是材料描述，混入文本，不可跳过
        decimal_nums = re.findall(r'(?<!\w)\d+\.\d+(?!\w)', line)
        if len(decimal_nums) >= 3:
            continue
        # 6-9 位纯 code → 新材料开始
        if re.match(r'^\d{6,9}$', line):
            _flush()
            cur_code = line
            cur_start = i
            continue
        # 含 code 的行（可能被 pypdf 拆到同行）→ 提取 code + 剩余当 text
        m = re.match(r'^(\d{6,9})\b\s*(.*)$', line)
        if m:
            _flush()
            cur_code = m.group(1)
            rest = m.group(2).strip()
            if rest:
                cur_text_lines.append(rest)
            continue
        # 否则当作 breed/spec/unit 的延续
        if cur_code is not None:
            cur_text_lines.append(line)
            # 防止单材料吞掉过多文本：最多 8 行
            if len(cur_text_lines) >= 8:
                _flush()

    _flush()
    return blocks


def _parse_breed_spec_unit_from_block(text):
    """从材料块文本中切出 (breed, spec, unit)。
    
    启发：
    - unit 是最后 1-2 个 token（来自 _UNIT_KEYWORDS）
    - breed 是开头的连续中文
    - spec 是中间部分
    """
    if not text:
        return ('', '', '')
    text = re.sub(r'\s+', ' ', text).strip()
    # 1. 找 unit
    unit_match = None
    for kw in sorted(_UNIT_KEYWORDS, key=len, reverse=True):
        # unit 必须在末尾或接近末尾
        m = re.search(r'(?:^|\s)(' + re.escape(kw) + r')\s*$', text)
        if m:
            unit_match = (m.start(1), m.group(1))
            break
        # 也允许 unit 后跟一个数字（价格）—— 但材料块不应有价格
        m = re.search(r'(?:^|\s)(' + re.escape(kw) + r')(?=\s|$)', text)
        if m and m.end(1) >= len(text) - 5:
            unit_match = (m.start(1), m.group(1))
            break
    if unit_match:
        unit = unit_match[1]
        breed_spec = text[:unit_match[0]].strip()
    else:
        unit = ''
        breed_spec = text

    # 2. 切 breed vs spec
    # breed 是开头的连续中文（含括号），到第一个 ASCII/数字/特殊字符为止
    m = re.match(r'^([\u4e00-\u9fff（）()·]+?)\s+(\S.*)$', breed_spec)
    if m:
        breed = m.group(1).strip()
        spec = m.group(2).strip()
    else:
        breed = breed_spec
        spec = ''
    return (breed, spec, unit)


def parse_page_type_F(text):
    """类型 F: 汉中县区表。
    
    页面中含以下结构：
      [顶部] 材料清单（仅名称 + 代码，可能被 PDF 拆开）
      [中] 编码 名称 规格型号 单位 除税价格（元）
      [中] 以下材料税率 13%
      [中] 材料列表（代码被换行拆开，裸代码出现在不同行）
      [中] 除税价格（元）
      [底] county names: 南郑 城固 洋县 ... 宁强（部分页可能只有 9 个）
      [底] 价格行：每行 N 个数字，对应一个材料的 N 个 county 价格
    
    策略：
      1. 定位 county header（连续的县名行，可能为 9 或 10 个）
      2. 从 county header 之前提取材料代码序列（以及 breed/spec/unit 块）
      3. 从 county header 之后提取价格序列
      4. 配对 material 与 price
    """
    rows = []
    raw_lines = [l.strip() for l in text.split('\n') if l.strip()]
    lines = _join_wrapped_lines(raw_lines)

    hz_counties_full = ['南郑', '城固', '洋县', '佛坪', '西乡', '镇巴', '留坝', '勉县', '略阳', '宁强']

    # 1. 找 table header 和 county header 位置
    table_header_idx = -1
    county_start_idx = -1
    n = 0  # dynamic county count

    for i, line in enumerate(lines):
        if table_header_idx == -1 and '编码 名称 规格型号 单位' in line:
            table_header_idx = i
        if county_start_idx == -1 and line.strip() in hz_counties_full:
            # 连续匹配若干个县名
            matched = []
            j = i
            while j < len(lines) and len(matched) < len(hz_counties_full):
                if lines[j].strip() in hz_counties_full:
                    matched.append(lines[j].strip())
                    j += 1
                else:
                    break
            # 需要至少 3 个连续县名才算 county header
            if len(matched) >= 3:
                county_start_idx = i
                n = len(matched)

    if county_start_idx == -1:
        return rows

    counties = [lines[k].strip() for k in range(county_start_idx, county_start_idx + n)]
    if not all(c in hz_counties_full for c in counties):
        return rows

    # 2. 从 table_header 之后到 county header 之前提取材料块（代码 + breed/spec/unit）
    # 启发：本次价格表的材料代码应在 table_header 之后。table_header 之前的代码是
    # “顶部材料清单”，不属于本次价格表。
    if table_header_idx != -1:
        scan_start = table_header_idx + 1
    else:
        scan_start = max(0, county_start_idx - 30)
    scan_end = county_start_idx  # county header 之前
    blocks = _group_hanzhong_material_blocks(lines, scan_start, scan_end)

    # 3. 从 county header 之后提取价格序列
    price_rows = []
    for line in lines[county_start_idx + n:]:
        line = line.strip()
        if not line:
            continue
        # 跳过页面装饰、备注等
        if '材料名称' in line or '汉中市' in line:
            continue
        if '价格信息' in line or '以下' in line or '税率' in line:
            continue
        if '联系电话' in line or '联系人' in line:
            continue
        # 提取数字
        nums = re.findall(r'\d+\.?\d*', line)
        # 只取正好 n 个数字的行
        if len(nums) == n:
            price_rows.append(nums)
        elif len(nums) > n:
            price_rows.append(nums[:n])
        elif 0 < len(nums) < n:
            # 不完整，跳过
            continue
        else:
            break

    # 4. 配对：blocks 与 price_rows
    for k, (code, breed_spec_unit_text) in enumerate(blocks):
        if k >= len(price_rows):
            break
        breed, spec, unit = _parse_breed_spec_unit_from_block(breed_spec_unit_text)
        for c_idx, county in enumerate(counties):
            price = _parse_number(price_rows[k][c_idx])
            if price is None:
                continue
            rows.append(MaterialRow(
                code=code, breed=breed, spec=spec, unit=unit,
                county=county, price=price, tax_price=None,
            ))
    return rows


def parse_page_type_G(text, page_obj=None):
    """类型 G: 商洛 — 使用 pdfplumber 提取 6 列表。
    
    特殊结构：PDF 为两列布局，表头后部分行仅有价格（无材料信息），
    另一部分行有完整材料信息。需使用 layout-aware 提取。
    
    过滤规则：只保留 col1(breed) 和 col2(spec) 都有内容的行。
    
    注意：需要传 pdfplumber Page 对象，不能仅传文本。
    """
    rows = []
    if page_obj is None:
        return rows
    try:
        import pdfplumber
        tables = page_obj.extract_tables() or []
        for tbl in tables:
            if not tbl or len(tbl) < 2:
                continue
            # 取列数 >= 5 且第一列以外的某个列有 breed
            for row in tbl:
                if not row or len(row) < 5:
                    continue
                cells = [(c or '').replace('\n', ' ').strip() for c in row]
                # 找材料名称和规格型号（跳过第一列空位）
                breed = ''
                spec = ''
                unit = ''
                price_a = None
                price_b = None
                # 列布局：0=code(empty), 1=breed, 2=spec, 3=unit, 4=no_tax, 5=tax
                if len(cells) >= 6:
                    breed = cells[1]
                    spec = cells[2]
                    unit = cells[3]
                    price_a = _parse_number(cells[4])
                    price_b = _parse_number(cells[5])
                if not breed or not spec:
                    continue  # 跳过“仅有价格”的行
                if price_a is None and price_b is None:
                    continue
                # 判断 哪是除税价（未含税）哪是含税价
                # 默认 4=除税价 5=含税价（多数）
                # 但商洛部分行 是 4=含税价 5=除税价（不可区分，假设两者中较小的是除税价）
                no_tax = price_a
                tax_p = price_b
                if no_tax is not None and tax_p is not None and tax_p < no_tax:
                    no_tax, tax_p = tax_p, no_tax
                rows.append(MaterialRow(
                    code='', breed=breed, spec=spec, unit=unit,
                    county='', price=no_tax, tax_price=tax_p,
                ))
    except Exception:
        pass
    return rows


# ─── OCR 兑底（处理图像型 PDF） ──────────────────────────────────────────────
_OCR_CACHE: dict = {}  # page_index -> text （避免重复 OCR）
_OCR_ENABLED = True   # 进程级开关：未安装 tesseract / poppler 时设为 False


def _ocr_disabled_check():
    """检查 OCR 依赖是否可用。不可用时返回 False。"""
    global _OCR_ENABLED
    if not _OCR_ENABLED:
        return False
    import shutil
    if not shutil.which('tesseract'):
        return False
    return True


def _ocr_page(pdf_path, page_index_0based, dpi=200, lang='chi_sim+eng'):
    """OCR 渲染并识别 PDF 的第 page_index_0based 页，返回文字。
    
    安康部分期是扫描图像 PDF，pypdf 提取不到文本，pdfplumber 只能给出旋转后的
    乱码。这里用 pdf2image 渲染 + tesseract OCR，必要时旋转 270°。
    """
    cache_key = (pdf_path, page_index_0based, dpi, lang)
    if cache_key in _OCR_CACHE:
        return _OCR_CACHE[cache_key]
    try:
        from pdf2image import convert_from_path
        import pytesseract
    except Exception:
        return ''
    import time
    t0 = time.time()
    try:
        imgs = convert_from_path(pdf_path, dpi=dpi,
                                 first_page=page_index_0based + 1,
                                 last_page=page_index_0based + 1)
    except Exception as e:
        print(f'  [OCR] render fail p{page_index_0based+1}: {e}')
        return ''
    if not imgs:
        return ''
    img = imgs[0]
    # 多次旋转尝试：270° 对陕西扫描 PDF 有效
    best_text = ''
    best_chinese = 0
    for angle in (270, 0, 90, 180):
        try:
            rotated = img.rotate(angle, expand=True) if angle else img
            text = pytesseract.image_to_string(rotated, lang=lang, config='--psm 6')
            cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
            if cn > best_chinese:
                best_text = text
                best_chinese = cn
            if cn > 100:
                break  # 够了
        except Exception:
            continue
    elapsed = time.time() - t0
    print(f'  [OCR] p{page_index_0based+1}: {elapsed:.1f}s, text {len(best_text)} chars, {best_chinese} CN')
    _OCR_CACHE[cache_key] = best_text
    return best_text


# ─── 主入口 ────────────────────────────────────────────────────────────────

def parse_pdf_pages(pdf_path, default_city):
    """解析整个 PDF，返回所有 (page_no, page_type, rows) 的列表。
    
    default_city: 当 city 字段不能从 PDF 内容推断时使用（如 '陕西'、'渭南' 等）。
    
    策略：
      1. 尝试 pypdf 提取文本 → 检测页面类型 → 走对应 parser
      2. 如果 pypdf 提取内容太少（< 100 chars），启用 OCR 兑底重新提取
    """
    reader = pypdf.PdfReader(pdf_path)
    # 同时打开 pdfplumber（用于 Type G）
    plumber = None
    try:
        import pdfplumber
        plumber = pdfplumber.open(pdf_path)
        plumber_pages = list(plumber.pages)
    except Exception:
        plumber = None
        plumber_pages = []
    
    results = []
    ocr_used = 0
    for pno, page in enumerate(reader.pages):
        text = page.extract_text() or ''
        # 如果 pypdf 提取内容太少（< 50 chars），是图像 PDF；启 OCR
        ocr_done = False
        if len(text.strip()) < 50 and _ocr_disabled_check():
            text = _ocr_page(pdf_path, pno)
            ocr_done = True
            ocr_used += 1
        if not text:
            continue
        page_type, info = detect_page_type(text)
        if page_type == 'skip':
            continue
        try:
            if page_type == 'A':
                rows = parse_page_type_A(text, info['counties'])
            elif page_type == 'D':
                rows = parse_page_type_D(text, info['counties'])
            elif page_type == 'E':
                rows = parse_page_type_E(text, info['counties'])
            elif page_type == 'B':
                rows = parse_page_type_B(text)
            elif page_type == 'C':
                rows = parse_page_type_C(text)
            elif page_type == 'F':
                rows = parse_page_type_F(text)
            elif page_type == 'G':
                # pdfplumber 处理
                pp = plumber_pages[pno] if pno < len(plumber_pages) else None
                rows = parse_page_type_G(text, pp)
            else:
                continue
            tag = 'OCR' if ocr_done else 'text'
            results.append((pno + 1, page_type, rows, tag))
        except Exception as e:
            # 单页失败不阻塞整本
            results.append((pno + 1, f'error:{e}', [], tag))
    
    if plumber is not None:
        plumber.close()
    if ocr_used:
        print(f'  [parse_pdf_pages] {ocr_used} pages used OCR')
    # 兼容旧调用方：只返回 (pno, ptype, rows)，丢了 tag
    return [(r[0], r[1], r[2]) for r in results]


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print('Usage: pdf_parser.py <pdf_path> [city]')
        sys.exit(1)
    path = sys.argv[1]
    city = sys.argv[2] if len(sys.argv) > 2 else '?'
    results = parse_pdf_pages(path, city)
    total = 0
    for pno, ptype, rows in results:
        if rows:
            print(f'Page {pno} ({ptype}): {len(rows)} rows')
            for r in rows[:2]:
                print(f'  {r.code} | {r.breed[:20]:20} | {r.spec[:20]:20} | {r.unit:5} | county={r.county:6} | price={r.price} | tax={r.tax_price}')
            total += len(rows)
    print(f'\nTotal: {total} rows')

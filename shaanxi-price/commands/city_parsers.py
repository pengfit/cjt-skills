"""陕西各设区市 / 省本级 PDF 解析器（按 city 维度组织）。

约定：
- 每个 city 一个独立函数，签名一致：`parse_<city>(text, page_obj=None) -> List[MaterialRow]`
- 函数内部自动判断页面布局（多布局兼容时优先识别）
- 不识别的页面（工人工资、安装工程、租赁等）返回空列表

city → 函数 映射由 `CITY_PARSERS` 字典提供。
"""
import re
from dataclasses import dataclass
from typing import List, Optional


# ─── 数据结构 ──────────────────────────────────────────────────────────────
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


# ─── 共享工具 ──────────────────────────────────────────────────────────────
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


_UNIT_KEYWORDS = [
    '台班', '张·天', '㎡·天', 'm•天', 'm·天', 'm³·天', 'm2·天',
    '千块', '百元', '千克', 'Km', 'km', 'm³', 'm2', '㎡', 'm',
    '天', '月', '年', '次', '套', '把', '片', '根', '块', '吨', '个',
    'T', 't', 'M', 'm',
]


def _is_boundary_line(line):
    """判断是否为逻辑行边界（不应与后续行合并）。"""
    line = line.strip()
    if not line:
        return True
    # 纯代码行（只有 digits） → 视为边界（新材料的开始）
    if re.match(r'^\d{6,9}$', line):
        return True
    # 代码 + 其余内容（如 "010101303 热轧光圆钢筋"）→ 仅当以价格结尾才是边界
    if re.match(r'^\d{6,9}\s+\S', line):
        return re.search(r'\d+\.?\d*\s+\d+\.?\d*\s*$', line) is not None
    if re.match(r'^\d{2}\s+[\u4e00-\u9fff]', line):
        return True
    if re.match(r'^编码\s', line) or '材料名称' in line:
        return True
    if line.startswith('除税价') or line.startswith('含税价') or '除税价格' in line:
        return True
    if '含税价格' in line:
        return True
    if line == '示范区' or '县区' in line or '各县' in line:
        return True
    # 汉中县名（短名）
    hz_names = {'南郑', '城固', '洋县', '佛坪', '西乡', '镇巴', '留坝', '勉县', '略阳', '宁强'}
    if line in hz_names:
        return True
    if re.match(r'^汉中市|^咸阳市|^安康市|^商洛市|^铜川市|^渭南市|^榆林市|^延安市|^宝鸡市', line):
        return True
    if re.match(r'^价格信息', line):
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


def _line_ends_with_prices(line):
    line = line.strip()
    if not line:
        return False
    return bool(re.search(r'(\d+\.?\d*)\s+(\d+\.?\d*)\s*$', line))


def _line_ends_with_single_price(line):
    line = line.strip()
    return bool(re.search(r'\d+\.?\d*\s*$', line) and not re.search(r'[a-zA-Z\u4e00-\u9fff]\s*$', line))


def _join_wrapped_lines(lines):
    """合并被 PDF 换行拆开的逻辑行（启发：上一行不以价格结尾且不是边界行）。"""
    out = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if _is_boundary_line(line):
            out.append(line)
            i += 1
            continue
        joined = line
        while i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if not next_line:
                i += 1
                continue
            if _is_boundary_line(next_line):
                break
            if _line_ends_with_prices(joined) or _line_ends_with_single_price(joined):
                break
            joined = joined + ' ' + next_line
            i += 1
        out.append(joined)
        i += 1
    return out


def _split_breed_spec_unit(line, code_end):
    """从 material 行（去掉 code 部分）切出 (breed, spec, unit)。"""
    rest = line[code_end:].strip()
    if not rest:
        return ('', '', '')
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
    bm = re.match(r'^([\u4e00-\u9fff（）()]+?)\s+(\S.*)$', breed_spec)
    if bm:
        breed = bm.group(1).strip()
        spec = bm.group(2).strip()
    else:
        breed = breed_spec
        spec = ''
    return (breed, spec, unit)


def _parse_code_line(line):
    """解析一行 material 行（如 '010101303 热轧光圆钢筋 HPB300 Φ6~8 t'）。"""
    m = re.match(r'^(\d{6,9})\s+(.+)$', line)
    if not m:
        return None
    code = m.group(1)
    breed, spec, unit = _split_breed_spec_unit(line, m.end(1))
    return (code, breed, spec, unit)


def _category_line(line):
    """检测是否为类目行（'01  黑色及有色金属'）。"""
    m = re.match(r'^\d{2}\s+[\u4e00-\u9fff（）()]+', line)
    return m.group(0).strip() if m else None


# ─── 县城/区识别 ────────────────────────────────────────────────────────────
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
    """判断是否为县/区/市名 token。"""
    tok = tok.strip()
    if not tok or len(tok) > 8:
        return False
    if tok in _COUNTY_BLOCKLIST:
        return False
    if any(tok.endswith(s) for s in _COUNTY_END):
        return True
    return False


def _extract_counties_from_text(text):
    """从文本中提取连续的 county 名 token。"""
    raw_tokens = re.split(r'[\s\n]+', text)
    candidates = []
    for tok in raw_tokens:
        if _is_county_token(tok):
            candidates.append(tok.strip())
    seen = set()
    uniq = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


# ─── 页面类型检测（基础工具） ──────────────────────────────────────────────
def _has_table_marker(text):
    """检测页面是否包含材料价格表头（编码+名称）。"""
    return bool(re.search(r'(?:^|\n)\s*(?:材料编码|编码)\s+(?:材料名称|名称)\s+(?:规格型号|规格及型号|型号规格)', text))


def _is_skip_page(text):
    """检测是否应跳过（非材料价格表）。"""
    if '日工资' in text or '人工单价' in text:
        return True
    if '工程量计算规则' in text:
        return True
    if '价格信息' in text and len(text) < 200:
        return True
    if '施工仪器仪表' in text and '编码' not in text:
        return True
    return False


# ═══════════════════════════════════════════════════════════════════════════
#  各 city 解析器
# ═══════════════════════════════════════════════════════════════════════════

# ─── 陕西 省本级 (B 布局: 6 列 单价表) ────────────────────────────────────
def _parse_type_B(text):
    """B 布局: 单价表 6 列（编码 + 名称 + 规格 + 单位 + 除税价 + 含税价）。"""
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
        nums = re.findall(r'\d+\.?\d*', line)
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
            if len(nums) >= 3:
                no_tax = _parse_number(nums[-3])
                if no_tax is not None:
                    rows.append(MaterialRow(
                        code=code, breed=breed, spec=spec, unit=unit,
                        category=cur_category,
                        price=no_tax, tax_price=tax_p,
                    ))
    return rows


def parse_shaanxi_province(text, page_obj=None):
    """陕西省本级《陕西工程造价信息》月刊 — B 布局。"""
    if _is_skip_page(text):
        return []
    if not _has_table_marker(text) and not re.search(r'^\d{6,9}\s+', text, re.MULTILINE):
        return []
    return _parse_type_B(text)


# ─── 咸阳 (B + E 布局) ────────────────────────────────────────────────────
def _parse_type_E(text, counties):
    """E 布局: county 成组，每组 2 个价格（除税+含税）。
    
    结构：每行一个 material，下一行是 2N 个数字（county×2）。
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
        if not re.search(r'\d', next_line):
            i += 1
            continue

        prices = re.findall(r'\d+\.?\d*', next_line)
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


def parse_xianyang(text, page_obj=None):
    """咸阳《咸阳工程造价信息》— 主要 B 布局，部分 last section 是 E 布局。
    
    启发：若页面同时含除税价+含税价且价格行有 2N 个数字（≥20），是 E；否则 B。
    """
    if _is_skip_page(text):
        return []
    if not _has_table_marker(text) and not re.search(r'^\d{6,9}\s+', text, re.MULTILINE):
        return []

    counties = _extract_counties_from_text(text)
    # E 布局：含 county 且 2N 个价格
    if counties and '除税价' in text and '含税价' in text:
        # 启发：找价格行有 ≥ 2N 个数字的迹象
        raw_lines = [l.strip() for l in text.split('\n') if l.strip()]
        lines = _join_wrapped_lines(raw_lines)
        n = len(counties)
        for line in lines:
            nums = re.findall(r'\d+\.?\d*', line)
            if len(nums) >= 2 * n and '除税价' not in line and '含税价' not in line:
                # E 布局
                return _parse_type_E(text, counties)

    return _parse_type_B(text)


# ─── 铜川 (C 布局: 7 列含税率) ──────────────────────────────────────────
def _parse_type_C(text):
    """C 布局: 7 列（含税+除税+税率），铜川专用。"""
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


def parse_tongchuan(text, page_obj=None):
    """铜川《铜川工程造价信息》— C 布局（含税价格+除税价格+税率%）。"""
    if _is_skip_page(text):
        return []
    if not _has_table_marker(text) and not re.search(r'^\d{6,9}\s+', text, re.MULTILINE):
        return []
    return _parse_type_C(text)


# ─── 渭南 (B 布局) ────────────────────────────────────────────────────────
def parse_weinan(text, page_obj=None):
    """渭南《渭南工程造价信息》(双月刊) — B 布局。"""
    if _is_skip_page(text):
        return []
    if not _has_table_marker(text) and not re.search(r'^\d{6,9}\s+', text, re.MULTILINE):
        return []
    return _parse_type_B(text)


# ─── 榆林 (B 布局) ────────────────────────────────────────────────────────
def parse_yulin(text, page_obj=None):
    """榆林《榆林工程造价信息》— B 布局。"""
    if _is_skip_page(text):
        return []
    if not _has_table_marker(text) and not re.search(r'^\d{6,9}\s+', text, re.MULTILINE):
        return []
    return _parse_type_B(text)


# ─── 汉中 (F 布局：顶材料清单 + 底 county 价格表) ─────────────────────────
def _group_hanzhong_material_blocks(lines, start_idx, end_idx):
    """汉中 PDF 材料块分组：按 6-9 位 code 拆分。
    
    每块 = code 行 + 后续非装饰、非 county、非价格行（最多 8 行）。
    返回 [(code, breed_spec_unit_text), ...]
    """
    hz_counties_full = ['南郑', '城固', '洋县', '佛坪', '西乡', '镇巴', '留坝', '勉县', '略阳', '宁强']
    hz_decorative = ['编码', '名称', '材料名称', '规格型号', '规格及型号', '单位', '类别', '除税价格', '含税价格', '税率',
                     '以下材料税率', '以下税率', '汉中市各县', '材料信息价', '价格信息', '价 格 信 息', '备注']
    blocks = []
    cur_code = None
    cur_text_lines = []

    def _flush():
        nonlocal cur_code, cur_text_lines
        if cur_code is not None:
            text = ' '.join(cur_text_lines).strip()
            text = re.sub(r'\s+', ' ', text).strip()
            blocks.append((cur_code, text))
        cur_code = None
        cur_text_lines = []

    for i in range(start_idx, end_idx):
        line = lines[i].strip()
        if not line:
            continue
        is_decorative = (line in hz_decorative or any(d in line for d in ['编码 名称', '以下材料税率', '汉中市', '价格信息', '联系电话', '联系人']))
        if is_decorative:
            continue
        if line in hz_counties_full:
            continue
        # 纯价格行（被空白分隔的小数 ≥3 个）跳过
        decimal_nums = re.findall(r'(?<!\w)\d+\.\d+(?!\w)', line)
        if len(decimal_nums) >= 3:
            continue
        if re.match(r'^\d{6,9}$', line):
            _flush()
            cur_code = line
            continue
        m = re.match(r'^(\d{6,9})\b\s*(.*)$', line)
        if m:
            _flush()
            cur_code = m.group(1)
            rest = m.group(2).strip()
            if rest:
                cur_text_lines.append(rest)
            continue
        if cur_code is not None:
            cur_text_lines.append(line)
            if len(cur_text_lines) >= 8:
                _flush()

    _flush()
    return blocks


def _parse_breed_spec_unit_from_block(text):
    """从材料块文本中切出 (breed, spec, unit)。"""
    if not text:
        return ('', '', '')
    text = re.sub(r'\s+', ' ', text).strip()
    unit_match = None
    for kw in sorted(_UNIT_KEYWORDS, key=len, reverse=True):
        m = re.search(r'(?:^|\s)(' + re.escape(kw) + r')\s*$', text)
        if m:
            unit_match = (m.start(1), m.group(1))
            break
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
    m = re.match(r'^([\u4e00-\u9fff（）()·]+?)\s+(\S.*)$', breed_spec)
    if m:
        breed = m.group(1).strip()
        spec = m.group(2).strip()
    else:
        breed = breed_spec
        spec = ''
    return (breed, spec, unit)


def _parse_type_F(text):
    """F 布局: 汉中县区表（county header + 价格行 + 顶部材料清单）。"""
    rows = []
    raw_lines = [l.strip() for l in text.split('\n') if l.strip()]
    lines = _join_wrapped_lines(raw_lines)
    hz_counties_full = ['南郑', '城固', '洋县', '佛坪', '西乡', '镇巴', '留坝', '勉县', '略阳', '宁强']

    table_header_idx = -1
    county_start_idx = -1
    n = 0

    for i, line in enumerate(lines):
        if table_header_idx == -1 and '编码 名称 规格型号 单位' in line:
            table_header_idx = i
        if county_start_idx == -1 and line.strip() in hz_counties_full:
            matched = []
            j = i
            while j < len(lines) and len(matched) < len(hz_counties_full):
                if lines[j].strip() in hz_counties_full:
                    matched.append(lines[j].strip())
                    j += 1
                else:
                    break
            if len(matched) >= 3:
                county_start_idx = i
                n = len(matched)

    if county_start_idx == -1:
        return rows

    counties = [lines[k].strip() for k in range(county_start_idx, county_start_idx + n)]
    if not all(c in hz_counties_full for c in counties):
        return rows

    if table_header_idx != -1:
        scan_start = table_header_idx + 1
    else:
        scan_start = max(0, county_start_idx - 30)
    scan_end = county_start_idx
    blocks = _group_hanzhong_material_blocks(lines, scan_start, scan_end)

    price_rows = []
    for line in lines[county_start_idx + n:]:
        line = line.strip()
        if not line:
            continue
        if '材料名称' in line or '汉中市' in line:
            continue
        if '价格信息' in line or '以下' in line or '税率' in line:
            continue
        if '联系电话' in line or '联系人' in line:
            continue
        nums = re.findall(r'\d+\.?\d*', line)
        if len(nums) == n:
            price_rows.append(nums)
        elif len(nums) > n:
            price_rows.append(nums[:n])
        elif 0 < len(nums) < n:
            continue
        else:
            break

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


def _parse_type_D(text, counties):
    """D 布局: 多县区表（仅除税价一行，county 名不带 区/县 结尾）。"""
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

        if i + 1 >= len(lines):
            i += 1
            continue
        next_line = lines[i + 1]
        if '除税价' in next_line or '除税价格' in next_line:
            price_str = re.sub(r'^(除税价|除税价格|（元）|（除税价）)\s*', '', next_line)
            prices = re.findall(r'\d+\.?\d*', price_str)
        else:
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


def parse_hanzhong(text, page_obj=None):
    """汉中《汉中建设工程造价信息》— 主要 F 布局，辅以 D 布局兜底。
    
    启发：若 county header 9-10 个县名连续 → F；否则若有 county + 仅除税价 → D。
    """
    if _is_skip_page(text):
        return []
    if not _has_table_marker(text) and not re.search(r'^\d{6,9}\s+', text, re.MULTILINE):
        return []

    hz_counties_full = ['南郑', '城固', '洋县', '佛坪', '西乡', '镇巴', '留坝', '勉县', '略阳', '宁强']
    hz_hits = sum(1 for c in hz_counties_full if c in text)
    if hz_hits >= 5:
        return _parse_type_F(text)

    counties = _extract_counties_from_text(text)
    if counties and '除税价' in text and '含税价' not in text:
        return _parse_type_D(text, counties)
    return []


# ─── 商洛 (G 布局: pdfplumber 两列布局) ──────────────────────────────────
# ─── 安康 (A 布局: 11 county 表 + 顶 materials) ────────────────────────────
def _parse_type_A(text, counties):
    """A 布局: 多县区表（除税价 + 含税价 各一行）。
    
    结构：
      [可选 category 行] '01 黑色及有色金属'
      [county header] '编码 材料名称 规格及型号 单位 类别 汉滨区 ... 紫阳县 恒口'
      [county header 续] '示范区'
      [material 行] '010101303 热轧光圆钢筋 HPB300 Φ6~8 t'
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
        if re.match(r'^(编码|材料编码)\s', line) or re.match(r'^汉中市|^咸阳市|^安康市', line):
            i += 1
            continue
        if '单位' in line and ('除税' in line or '含税' in line or len(line) < 50):
            i += 1
            continue
        parsed = _parse_code_line(line)
        if not parsed:
            i += 1
            continue
        code, breed, spec, unit = parsed
        if i + 2 >= len(lines) or '除税价' not in lines[i + 1] or '含税价' not in lines[i + 2]:
            i += 1
            continue
        no_tax_prices = re.findall(r'\d+\.?\d*', lines[i + 1].replace('除税价', ''))
        tax_prices = re.findall(r'\d+\.?\d*', lines[i + 2].replace('含税价', ''))
        if len(no_tax_prices) >= n:
            no_tax_prices = no_tax_prices[:n]
        else:
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


def parse_ankang(text, page_obj=None):
    """安康《安康建设工程造价信息》— A 布局（11 county 表 + 数字 PDF）。
    
    注意：2026.1-4 期是扫描图像型 PDF，pypdf 提不到文本，OCR 跑通但解析器不识别
    OCR 输出格式，sync 走 skipped_image_pdf 跳过。2026.5期是数字 PDF，可正常解析。
    """
    if _is_skip_page(text):
        return []
    counties = _extract_counties_from_text(text)
    # 安康 11 county：汉滨区/汉阴县/石泉县/宁陕县/平利县/白河县/紫阳县/岚皋县/镇坪县/旬阳市/恒口示范区
    ankang_keys = {'汉滨区', '汉阴县', '石泉县', '宁陕县', '平利县', '白河县', '紫阳县', '岚皋县', '镇坪县', '旬阳市', '恒口'}
    if not counties or not any(c in ankang_keys for c in counties):
        return []
    if '除税价' not in text or '含税价' not in text:
        return []
    return _parse_type_A(text, counties)


def parse_shangluo(text, page_obj=None):
    """商洛《商洛工程造价管理信息》(季刊) — G 布局（双列，pdfplumber 提取）。"""
    if _is_skip_page(text):
        return []
    if page_obj is None:
        return []
    # 商洛 PDF 特征：标题里有"商洛"和"工程造价管理信息"
    if '商洛' not in text or '工程造价管理信息' not in text or len(text) <= 200:
        return []
    return _parse_type_G(page_obj)


def _parse_type_G(page_obj):
    """G 布局: 商洛双列布局，pdfplumber 提取 6 列表。"""
    rows = []
    try:
        tables = page_obj.extract_tables() or []
        for tbl in tables:
            if not tbl or len(tbl) < 2:
                continue
            for row in tbl:
                if not row or len(row) < 5:
                    continue
                cells = [(c or '').replace('\n', ' ').strip() for c in row]
                breed = ''
                spec = ''
                unit = ''
                price_a = None
                price_b = None
                if len(cells) >= 6:
                    breed = cells[1]
                    spec = cells[2]
                    unit = cells[3]
                    price_a = _parse_number(cells[4])
                    price_b = _parse_number(cells[5])
                if not breed or not spec:
                    continue
                if price_a is None and price_b is None:
                    continue
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


# ─── city → parser 映射 ──────────────────────────────────────────────────
CITY_PARSERS = {
    '陕西': parse_shaanxi_province,
    '咸阳': parse_xianyang,
    '铜川': parse_tongchuan,
    '渭南': parse_weinan,
    '榆林': parse_yulin,
    '汉中': parse_hanzhong,
    '商洛': parse_shangluo,
    '安康': parse_ankang,  # 仅 5期（数字 PDF）有效；1-4期（扫描型）需 OCR，先走 skipped_image_pdf
}


def parse_page(text, city, page_obj=None):
    """按 city 分发到对应 parser。
    
    Args:
        text: pypdf/pdftotext 提取的页面文本
        city: 设区市名 或 '陕西'（省本级）
        page_obj: pdfplumber Page 对象（部分 city 如商洛需要）
    Returns:
        List[MaterialRow]
    """
    parser = CITY_PARSERS.get(city)
    if not parser:
        return []
    try:
        return parser(text, page_obj)
    except Exception as e:
        print(f'  [parse] {city} failed: {e}')
        return []

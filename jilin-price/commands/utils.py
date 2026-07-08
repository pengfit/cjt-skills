#!/usr/bin/env python3
"""吉林 skill 工具函数。

源站特性（必须在 utils 层处理）：
- 查询字符串按 GBK 解析（不是 UTF-8）。URL 编码必须用 GBK，
  否则"price_time=2026年1月份"等中文查询参数查不到数据。
- 表单字段：diqu / price_time / title / submit（全部 GET 或 POST 都可）。
- 表格形态：HTML table，每条记录 8 个 <td>，首列前一行有 height="30"。
- 一页 20 条记录，按月分页。
- 字段：地区、时间、名称、规格、单位、除税价、含税价、备注。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import yaml


# ── 配置加载 ──────────────────────────────────────────────────

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yml"


def load_config(path: Optional[str] = None) -> dict:
    """加载 config.yml，返回 dict。"""
    p = path or str(_CONFIG_PATH)
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ── URL 编码（GBK）─────────────────────────────────────────────

def gbk_urlencode(s: str) -> str:
    """对字符串做 URL 编码，中文按 GBK 编码（不是 UTF-8）。

    源站 PHP 用 GBK 解析查询字符串。用 UTF-8 编码（requests 默认）
    会导致中文参数查不到数据，这是踩过的坑。
    """
    from urllib.parse import quote
    return quote(s, safe="")


def build_list_url(
    base_url: str,
    city_id: int,
    diqu: str = "",
    price_time: str = "",
    title: str = "",
    page: int = 1,
) -> str:
    """构造列表页 URL。所有中文参数按 GBK 编码。

    Args:
        base_url: e.g. http://www.jlszjw.com/city/price_list.php
        city_id: 140（吉林市固定）
        diqu: 地区筛选。空 = 全部地区（吉林市整体）。如 '吉林市-永吉县'。
        price_time: 时间筛选。如 '2026年1月份'。空 = 不限。
        title: 名称模糊搜索。空 = 不限。
        page: 页码（1-based）
    """
    qs = {
        "city": city_id,
        "diqu": diqu,
        "price_time": price_time,
        "title": title,
        "submit": "",
        "page": page,
    }
    parts = []
    for k, v in qs.items():
        if isinstance(v, int):
            parts.append(f"{k}={v}")
        else:
            parts.append(f"{k}={gbk_urlencode(v)}")
    return f"{base_url}?{'&'.join(parts)}"


# ── HTTP 抓取 ─────────────────────────────────────────────────

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def fetch_list_page(
    session,
    base_url: str,
    city_id: int,
    diqu: str = "",
    price_time: str = "",
    title: str = "",
    page: int = 1,
    timeout: int = 30,
    max_retries: int = 3,
) -> str:
    """抓列表页 HTML 原文。失败重试 max_retries 次。

    Returns:
        HTML 字符串（源站 charset=utf-8，Python 直接 utf-8 解码）。
    """
    import time
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            url = build_list_url(base_url, city_id, diqu, price_time, title, page)
            # Referer 必须是首页（不带 page），不然某些站点会拒绝。
            headers = dict(DEFAULT_HEADERS)
            headers["Referer"] = f"{base_url}?city={city_id}"
            r = session.get(url, headers=headers, timeout=timeout)
            r.raise_for_status()
            r.encoding = "utf-8"  # 源站 charset=utf-8（PHP 5.6 头部声明）
            return r.text
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(2)
    raise RuntimeError(f"列表页抓取失败（{max_retries} 次重试）: {last_err}")


# ── HTML 解析 ─────────────────────────────────────────────────

# 每条记录：8 个 <td>，首个 <td height="30">
ROW_RE = re.compile(
    r'<td\s+height="30">(.*?)</td>\s*'
    r'<td>(.*?)</td>\s*'
    r'<td>(.*?)</td>\s*'
    r'<td>(.*?)</td>\s*'
    r'<td>(.*?)</td>\s*'
    r'<td>(.*?)</td>\s*'
    r'<td>(.*?)</td>\s*'
    r'<td>(.*?)</td>',
    re.DOTALL,
)


def _clean_html(s: str) -> str:
    """去掉单元格里的 HTML 标签（源站偶尔会塞 <br> 等）。"""
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)
    return s.strip()


# ── 名称清洗 ──────────────────────────────────────────────────

# 道友要求：去掉前缀"（YYYY年补充）"、"（补充）"等括号说明。
# 例："（2025年补充）干混抹灰砂浆" → "干混抹灰砂浆"
# 例："(2025年补充)深褐色铝方通" → "深褐色铝方通"
# 例："【2025年补充】xxx" → "xxx"
# 例："（2024年调整）xxx" → "xxx"
PREFIX_BRACKET_RE = re.compile(
    r"^[\s　]*[\(（\[【]"      # 左括号（全/半角、方括号、中括号）
    r"[^)\]】]+"                # 括号内任意非右括号字符
    r"[\)）\]】]"               # 右括号
    r"[\s　]*"                  # 可能的空格
)


def strip_breed_prefix(breed: str) -> str:
    """去掉名称前缀的括号说明（年份补充/调整/补遗等）。

    多次匹配：可能存在多重前缀，如"（2025年补充）（甲类）水泥"。

    极端情况：breed 本身只是括号说明（如 "（2024年补充）"），返回原值让上层处理。
    """
    if not breed:
        return breed
    original = breed
    while True:
        new = PREFIX_BRACKET_RE.sub("", breed, count=1).strip()
        if new == breed:
            break
        breed = new
    return breed or original


def derive_breed_from_spec(spec: str) -> str:
    """从 spec 里推导 breed fallback。

    源站偶尔会有 breed="（2024年补充）" 这种 "补充材料标题行"，
    spec 里其实是描述。提取 spec 的第一句或前 20 字作为 breed 提示。
    """
    if not spec:
        return ""
    # 按换行/句号/逗号分割，取第一段
    import re as _re
    first = _re.split(r"[\n;,。]", spec, maxsplit=1)[0].strip()
    if not first:
        return ""
    # 去掉数字前缀（如 "1.名称:xxx" → "名称:xxx"）
    first = _re.sub(r"^\d+[\.、:：]\s*", "", first)
    return first[:30].strip()


# ── breed + spec 复合拆分 ───────────────────────────────────────────
# 道友要求：breed 中存在"复合信息"时（如末尾紧跟型号代码），拆成 breed + spec。
# 常见模式：
#   1. 末尾括号（半角/全角）内是 ASCII 规格
#      "分水器电镀双阀1寸（DC7）"                     → ("分水器电镀双阀1寸", "DC7")
#      "APF-D100丁基自粘高分子防水卷材（TPO）"         → (..., "TPO")
#   2. 末尾 ASCII 型号代码（前置中文、含数字、非纯单位）
#      "球墨铸铁蝶阀D71X-16"                          → ("球墨铸铁蝶阀", "D71X-16")
#      "低压主受柜  D01"                               → ("低压主受柜", "D01")
#      "PE-RTⅡ型耐热塑料管 110*10.0  SDR11"          → (..., "SDR11")  优先取短型号
#   3. 末尾数字开头的规格串（前置中文、ASCII 字符、含运算符号）
#      "聚乙烯给水管（PE）630×57.2PN1.6MPA"            → ("聚乙烯给水管（PE）", "630×57.2PN1.6MPA")
#      "PE100聚乙烯给水管1.6MPa  SDR11"               → ("PE100聚乙烯给水管", "1.6MPa  SDR11")
#      "钢丝网骨架PE复合管1.6Mpa"                      → ("钢丝网骨架PE复合管", "1.6Mpa")
# 安全约束：
#   - 提取的 spec/model 必须是纯 ASCII（含字母+数字、非纯单位），
#     防止把 "箱体500*600*180*1.2" 这种混乱描述误拆。
#   - prefix 必须有 ≥ 2 个连续中文字符（"箱体"才 2 个字，太短就让拆分)。
#   - 纯数字+单位（"2.0mm"/"500W"）不算规格代码，不拆。

# 纯单位结尾识别（数字+常见单位，不是型号代码）
_PURE_UNIT_RE = re.compile(
    r"^\d+(?:\.\d+)?"                          # 数字（支持小数）
    r"(?:mm2|mm|cm2|cm|dm|m3|m|kg|t|"
    r"V|KV|kV|W|KW|kW|A|AH|MPa|Mpa|KN|Hz|°)"   # 常见单位
    r"$"
)
# 数字 + 数字运算符（含横线/斜杠/乘号等）— 规格型
_DIGIT_RUN_RE = re.compile(
    r"\d+(?:[.\-*+×xX/÷]\d+)+"   # 至少 1 组 [运算符]+数字
)
# ASCII 字符型型号代码（以大写字母开头，含数字）
_ASCII_MODEL_RE = re.compile(
    r"^[A-Z][A-Za-z0-9()\-_/.]*\d[A-Za-z0-9()\-_/.]*$"
)


def _has_cjk(s: str) -> bool:
    """字符串中是否含中文字符。"""
    return bool(re.search(r"[\u4e00-\u9fa5]", s or ""))


def _has_n_cjk(s: str, n: int) -> bool:
    """字符串中是否含 ≥ n 个连续中文字符。"""
    return bool(re.search(r"[\u4e00-\u9fa5]{" + str(n) + ",}", s or ""))


def _has_2cjk(s: str) -> bool:
    """字符串中是否含 ≥ 2 个连续中文字符（防止误拆短品种名）。"""
    return _has_n_cjk(s, 2)


def _is_pure_unit(s: str) -> bool:
    """是否是纯数字+单位（不应被当作型号或规格代码）。"""
    return bool(_PURE_UNIT_RE.match(s or ""))


def _merge_spec(new_spec: str, old_spec: str) -> str:
    """合并两个 spec，避免重复。用 ' | ' 分隔。"""
    new_spec = (new_spec or "").strip()
    old_spec = (old_spec or "").strip()
    if not new_spec:
        return old_spec
    if not old_spec:
        return new_spec
    if new_spec in old_spec:
        return old_spec
    if old_spec in new_spec:
        return new_spec
    return f"{new_spec} | {old_spec}"


def split_breed_spec(breed: str, spec: str = "") -> tuple[str, str]:
    """从 breed 中拆出末尾规格信息。

    Returns:
        (新breed, 新spec)。无匹配时原样返回。

    三条规则按优先级：
      1. 末尾括号（半角/全角）内是 ASCII 规格
      2. 末尾数字开头的规格串（ASCII、含运算符号）
      3. 末尾 ASCII 型号代码（前置 ≥ 2 中文字、含字母+数字）
    """
    if not breed:
        return breed, spec

    cleaned = str(breed).replace("\r", "").replace("\n", "")
    if not cleaned:
        return cleaned, spec

    # 规则1: 末尾括号（半角/全角）内是 ASCII 规格
    # 例: 分水器电镀双阀1寸（DC7） → 分水器电镀双阀1寸 + DC7
    m = re.match(
        r"^(?P<prefix>.+?)[（(](?P<paren>[A-Za-z0-9.\-/*×x\s]+?)[)）]\s*$",
        cleaned,
    )
    if m and re.search(r"[A-Za-z0-9]", m.group("paren")):
        nb = m.group("prefix").strip()
        ns = m.group("paren").strip()
        if nb and _has_2cjk(nb):
            return nb, _merge_spec(ns, spec)

    # 规则2: 末尾数字开头的规格串（含至少一个 [运算符]+数字，后续可空格分隔的 ASCII 字母单位）
    # 例: 聚乙烯给水管（PE）630×57.2PN1.6MPA → 聚乙烯给水管（PE） + 630×57.2PN1.6MPA
    # 例: PE-RTⅡ型耐热塑料管 32*3.6   SDR9     → PE-RTⅡ型耐热塑料管 + 32*3.6   SDR9
    # 例: 钢丝网骨架PE复合管1.6Mpa               → 钢丝网骨架PE复合管 + 1.6Mpa（prefix 够长时也接受纯单位）
    # 必须先于规则3执行，避免短型号（如 SDR11）抢前面的数字规格
    if _DIGIT_RUN_RE.search(cleaned):
        m2 = re.match(
            r"^(?P<prefix>.+?[\u4e00-\u9fa5]{2,}.*?)\s*"
            r"(?P<num_spec>\d+(?:[.\-*+×xX/÷]\d+)+"
            r"(?:\s*[A-Za-z][A-Za-z0-9()\-_/.×*]*)*)$",
            cleaned,
        )
        if m2:
            nb = m2.group("prefix").rstrip()
            ns = m2.group("num_spec").strip()
            # num_spec 是纯单位（如 1.6Mpa/12.5KN/450/750V）时，
            # 要求 prefix 含 ≥ 5 连续 CJK 字符才拆，防止短品种名被误拆。
            pure_unit_ok = (
                not _is_pure_unit(ns)
                or _has_n_cjk(nb, 5)
            )
            if (
                nb
                and ns
                and len(ns) >= 5
                and not _has_cjk(ns)
                and pure_unit_ok
            ):
                return nb, _merge_spec(ns, spec)

    # 规则3: 末尾 ASCII 型号代码（前置 ≥ 2 中文字、含字母+数字、非纯单位）
    # 例: 球墨铸铁蝶阀D71X-16 → 球墨铸铁蝶阀 + D71X-16
    m3 = re.match(
        r"^(?P<prefix>.+?[\u4e00-\u9fa5]{2,}.*?)\s*"
        r"(?P<model>[A-Z][A-Za-z0-9()\-_/.]*\d[A-Za-z0-9()\-_/.]*)$",
        cleaned,
    )
    if m3:
        nb = m3.group("prefix").rstrip()
        ns = m3.group("model").strip()
        if (
            nb
            and ns
            and len(ns) >= 3
            and _ASCII_MODEL_RE.match(ns)        # 整体纯 ASCII 型号
            and not _is_pure_unit(ns)            # 不是纯数字+单位
            and re.search(r"[A-Za-z]", ns)       # 含字母
            and re.search(r"\d", ns)             # 含数字
        ):
            return nb, _merge_spec(ns, spec)

    return cleaned, spec


# ── 价格解析 ──────────────────────────────────────────────────

def parse_price(s: str) -> Optional[float]:
    """解析价格字符串 → float。空/无效返回 None。"""
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    # 去掉 ￥ 元 , 等常见符号
    s = re.sub(r"[￥,，\s元]", "", s)
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


# ── 行解析 ────────────────────────────────────────────────────

def parse_rows(html: str) -> list[dict]:
    """从 HTML 里抽出所有价格记录行。

    Returns:
        [
            {
                'county': '吉林市',                # 地区
                'period': '2026年7月份',            # 时间（业务期）
                'breed_raw': '（2025年补充）干混抹灰砂浆',  # 源站原文（调试用）
                'breed': '干混抹灰砂浆',             # 清洗后（去括号前缀）
                'breed_clean': '干混抹灰砂浆',        # 拆分后（去末尾型号/规格）
                'spec': 'M5.0',                      # 拆出的规格 + 源站 spec 合并
                'unit': 't',
                'price': 360.0,                      # 除税价
                'tax_price': 370.0,                  # 含税价
                'remarks': '',
            },
            ...
        ]

    字段名约定（与 xinjiang-price / heze-price / shaanxi-price 一致）：
      - `breed`         = 清洗后（去 prefix 括号）的品种名
      - `breed_clean`   = 复合拆分后（去末尾型号/规格代码）的品种名
      - `spec`          = 拆出的规格 + 源站 spec 合并
    """
    rows = []
    for m in ROW_RE.finditer(html):
        county = _clean_html(m.group(1))
        period = _clean_html(m.group(2))
        breed_raw = _clean_html(m.group(3))
        spec = _clean_html(m.group(4))
        unit = _clean_html(m.group(5))
        price_s = _clean_html(m.group(6))
        tax_price_s = _clean_html(m.group(7))
        remarks = _clean_html(m.group(8))

        if not breed_raw or breed_raw == "材料名称":
            continue

        # 1. 清洗 breed_raw：去掉 "（YYYY年补充）" 之类的 prefix 括号。
        # 清洗后是 breed。
        breed = strip_breed_prefix(breed_raw)
        # 清洗后如果只剩括号（说明 breed_raw 本身是 "（2024年补充）" 这种标题行），
        # 从 spec 推导一个 fallback breed。
        if breed == breed_raw and breed.startswith("（") and breed.endswith("）"):
            breed = derive_breed_from_spec(spec) or breed

        # 2. 拆分 breed 中的复合规格信息（型号代码 / 末尾括号规格 / 末尾数字规格）。
        # 拆完后 breed_clean + spec。
        # 安全约束：
        #   - prefix 必须有 ≥ 2 连续中文字符（避免短品种名误拆）
        #   - 提取的 spec 必须是纯 ASCII、含字母+数字、非纯单位
        breed_clean, spec = split_breed_spec(breed, spec)

        # 过滤人工单价工种行（不是材料价格，应该从材料分析中剔除）
        # 源站里这些行：除税价列空、含税价列是区间（如 "260-280"），unit="工 日"。
        # 如果不剔除，parse_price 会把区间字符串当作无效值丢成 0，污染统计。
        if is_trade_unit(unit):
            continue

        rows.append({
            "county": county,
            "period": period,
            "breed_raw": breed_raw,
            "breed": breed,
            "breed_clean": breed_clean,
            "spec": spec,
            "unit": unit,
            "price": parse_price(price_s),
            "tax_price": parse_price(tax_price_s),
            "remarks": remarks,
        })
    return rows


# ── 人工单价（工种）过滤 ─────────────────────────────────────────────

# 源站发布材料价格时，偶尔会把人工单价（"木工"、"电工"等工种单价）作为单独行发布，
# 这类数据 unit 通常为 "工 日"，breed 是工种名。这些行：
#   1. 不属于材料价格，应该从材料分析中剔除；
#   2. 价格往往是区间（如 "260-280"），当前 parse_price 无法解析；
#   3. 入库会污染 avg_price / 涨跌幅等统计。
# 过滤规则：unit == "工 日" 或 "工日" 一律丢弃。
TRADE_UNITS = frozenset(("工 日", "工日"))


def is_trade_unit(unit: str) -> bool:
    """判断是否为人工单价（工种）行。"""
    return (unit or "").strip() in TRADE_UNITS


def parse_total_pages(html: str) -> int:
    """从分页区抽出总页数。

    源站分页格式：
        <div class="pagination">
          <li>...</li>
          <li><a href="...?page=2">下一页</a></li>
          <li><a href="...?page=7566">尾页</a></li>
        </div>
    末页 page=N 即总页数。
    """
    # 找最后一个 page=N（尾页）
    matches = re.findall(r"page=(\d+)", html)
    if not matches:
        return 1
    return max(int(p) for p in matches)


# ── county 清洗 ─────────────────────────────────────────────

# source 里 county 字段有 "吉林市" 和 "吉林市-吉林市" 两种写法。
# 都是"吉林市本身"。拆成短名避免重复。
def normalize_county(county: str, city: str = "吉林市") -> str:
    """'吉林市-吉林市' → '吉林市'。'吉林市' → '吉林市'。"""
    if not county:
        return ""
    if "-" in county:
        parts = county.split("-", 1)
        # 如果 city 前缀冗余（city == parts[0]），去掉
        if parts[0] == city:
            return parts[1].strip() or county
    return county.strip()


# ── period 标准化（供 dashboard prefix 查询）──────────

# Dashboard 用 prefix {period: "2026."} 查，所以 progress / ODS 文档的 period
# 字段必须以 "2026." 开头（如 "2026.1月份"、"2026.7月份"）。
# 但源站返回的是 "2026年1月份" 这种中文表达，需要转换。
DASHBOARD_PERIOD_RE = re.compile(r"^(\d{4})年(\d{1,2})月(份?)$")


def to_dashboard_period(period: str) -> str:
    """'2026年1月份' → '2026.1月份'。"""
    m = DASHBOARD_PERIOD_RE.match(period or "")
    if not m:
        return period
    return f"{m.group(1)}.{int(m.group(2))}月{m.group(3)}"
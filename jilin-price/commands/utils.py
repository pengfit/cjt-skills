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
                'county': '吉林市',      # 地区
                'period': '2026年7月份',  # 时间（业务期）
                'breed_raw': '（2025年补充）干混抹灰砂浆',
                'breed': '干混抹灰砂浆',  # 清洗后
                'spec': 'M5.0',
                'unit': 't',
                'price': 360.0,           # 除税价
                'tax_price': 370.0,       # 含税价
                'remarks': '',
            },
            ...
        ]
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

        breed_clean = strip_breed_prefix(breed_raw)
        # 清洗后如果只剩括号（说明 breed_raw 本身是 "（2024年补充）" 这种标题行），
        # 从 spec 推导一个 fallback breed。
        if breed_clean == breed_raw and breed_clean.startswith("（") and breed_clean.endswith("）"):
            breed_clean = derive_breed_from_spec(spec) or breed_clean

        # 过滤人工单价工种行（不是材料价格，应该从材料分析中剔除）
        # 源站里这些行：除税价列空、含税价列是区间（如 "260-280"），unit="工 日"。
        # 如果不剔除，parse_price 会把区间字符串当作无效值丢成 0，污染统计。
        if is_trade_unit(unit):
            continue

        rows.append({
            "county": county,
            "period": period,
            "breed_raw": breed_raw,
            "breed": breed_clean,
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
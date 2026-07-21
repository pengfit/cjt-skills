#!/usr/bin/env python3
"""宁夏 - 增量检测（v2, 2026-07-21）

源站 `jst.nx.gov.cn` 启用了 CT2-WAAP 反爬，直接 HTTP 取列表会被 412 / 滑块挑战拦截。
参照重庆 chongqing-price/commands/check.py 改写：用 `openclaw browser` 打开页面、
在 tab 里跑 JS 抽取候选期刊条目，再跟 ES update_date/period 比对，写 chip 状态。

判定策略：
  1. 优先按 publish_date 字符串字典序比较（YYYY-MM-DD）
  2. 没有日期时按 period_label "(year, issue_num)" 元组比较
  3. ES 无数据 → 状态 "error"（cron 表达"待首次同步"语义，统一用 error/has_update=false）
"""
import os
import re
import sys
import json
import time
import subprocess

STATUS_DIR = os.environ.get("GOV_CHECK_STATUS_DIR", "/tmp/gov-check-status")
SUMMARY_DIR = os.environ.get("GOV_PRICE_SUMMARY_DIR", "/tmp/gov-price-summary")

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.yml")

import yaml
from elasticsearch import Elasticsearch


# ── openclaw CLI 封装 ─────────────────────────────────────────
def _run_cli(args, timeout=30):
    r = subprocess.run(
        ["openclaw"] + list(args),
        capture_output=True, text=True, timeout=timeout,
        env={**os.environ},
    )
    return r.stdout, r.stderr


# openclaw doctor 警告会把框字符污染 stdout。下面这套过滤是从重庆 check.py
# 直接搬来的（同样场景跑过、稳）。
_DOCTOR_FRAME_CHARS = ('│', '┌', '┐', '└', '┘', '┤', '├', '┬', '┴', '┼',
                       '─', '╮', '╯', '╭', '╰', '◇')
_DOCTOR_KEYWORDS = ('Doctor', 'warnings', 'config-health', 'SQLite state',
                    'legacy config', 'Left')


def _strip_doctor_box(text: str) -> str:
    cleaned = []
    for line in text.splitlines():
        if any(c in line for c in _DOCTOR_FRAME_CHARS):
            continue
        if any(kw in line for kw in _DOCTOR_KEYWORDS):
            continue
        cleaned.append(line)
    return '\n'.join(cleaned).strip()


def _eval_js(js_body: str, timeout=30) -> str:
    out, _ = _run_cli(["browser", "evaluate", "--fn", js_body], timeout=timeout)
    s = _strip_doctor_box(out).strip()
    # 飞书 interactive 卡片分支时 openclaw 会返回 JSON 字符串字面量（首尾带引号）
    if s.startswith('"') and s.endswith('"'):
        s = s[1:-1]
    return s.replace('\\"', '"').replace('\\\\"', '"')


# ── 浏览器 tab 管理 ─────────────────────────────────────────
SITE_URL = "https://jst.nx.gov.cn/ztzl/gczj/zjtt/index.html"
# tab title 通常包含"宁夏住建厅"或"宁夏"，挑最短最稳的关键词
TAB_LABEL = "宁夏"


def _check_browser_tab() -> str | None:
    """查找已打开的宁夏 tab；没有则主动 open SITE_URL。

    Returns:
        tab id（形如 't3'），失败 None。
    """
    out, _ = _run_cli(["browser", "tabs"])
    for line in out.splitlines():
        if TAB_LABEL in line:
            m = re.search(r'\[?t(\d+)\]?', line)
            if m:
                return f"t{m.group(1)}"
    # 没有就 open（cron 场景下无人值守）
    print(f"[*] 未找到已开 tab，主动打开: {SITE_URL}")
    out, err = _run_cli(["browser", "open", SITE_URL], timeout=60)
    if not out and err:
        print(f"[!] open 失败: {err.strip()[:200]}")
        return None
    time.sleep(3)
    out, _ = _run_cli(["browser", "tabs"])
    for line in out.splitlines():
        if TAB_LABEL in line:
            m = re.search(r'\[?t(\d+)\]?', line)
            if m:
                return f"t{m.group(1)}"
    return None


def _focus_tab(tab_id: str) -> bool:
    out, _ = _run_cli(["browser", "focus", tab_id])
    return "focused" in out.lower() or "ok" in out.lower()


# ── JS 抽取（替代 HTTP/BeautifulSoup） ─────────────────────
def get_site_periods() -> list[dict]:
    """在 tab 里跑 JS，取所有候选期刊条目（标题含"宁夏工程造价"且含"年第X期"）。

    返回元素：{title, href, date}
      - title: 期刊完整标题（如 '关于发布2026年第2期《宁夏工程造价》的通知'）
      - href: 详情页 URL
      - date: 邻近节点里的日期字符串（可能为空）

    列表按页面 DOM 顺序（一般是倒序），取第一条即"最新一期"。
    """
    js = r'''(function(){
var out = [];
var anchors = document.querySelectorAll("a");
for (var i=0;i<anchors.length;i++){
  var a = anchors[i];
  var t = (a.innerText || a.textContent || "").trim().replace(/\s+/g, " ");
  if (!t) continue;
  if (!/宁夏工程造价/.test(t)) continue;
  if (!/第\s*[一二三四五六七八九十0-9]+\s*期/.test(t)) continue;
  var href = a.href || "";
  if (!href) continue;
  var date = "";
  var p = a.closest("li, .item, .news-list, .list-item, .news, tr, div");
  if (p) {
    var ts = p.querySelectorAll("span, em, i, .date, .time, .riqi, .news-date");
    for (var j=0;j<ts.length;j++){
      var tx = (ts[j].innerText||ts[j].textContent||"").trim();
      if (/\d{4}\D+\d{1,2}\D+\d{0,2}/.test(tx)) { date = tx; break; }
    }
  }
  out.push({title:t, href:href, date:date});
}
return JSON.stringify(out.slice(0, 30));
})()'''
    try:
        raw = _eval_js(js, timeout=30)
        if raw and raw != "null":
            return json.loads(raw)
    except Exception as e:
        print(f"[!] JS 解析失败: {e}")
    return []


# ── 文本规范化 ─────────────────────────────────────────────
def _norm_date(d: str) -> str:
    """把 '2026年5月18日' / '2026-05-18' / '2026/5/18' 规范成 YYYY-MM-DD"""
    if not d:
        return ""
    m = re.search(r'(\d{4})\D+(\d{1,2})\D+(\d{1,2})', d)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ""


_CN_NUM = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
           '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}


def _cn_to_int(s: str) -> int:
    """一/十一/二十三 → 整数（百以内常用）。"""
    if not s:
        return 0
    s = s.strip()
    if s.isdigit():
        return int(s)
    if s in _CN_NUM:
        return _CN_NUM[s]
    if s.startswith('十'):
        rest = s[1:]
        return 10 + (_CN_NUM.get(rest, 0) if rest else 0)
    if '十' in s:
        a, _, b = s.partition('十')
        return _CN_NUM.get(a, 0) * 10 + _CN_NUM.get(b, 0)
    return 0


def parse_period_from_title(title: str) -> tuple[str, int, int]:
    """解析 title -> (period_label, year, issue_num)。

    与 collector._legacy.parse_period_label 同构，便于对账。
    """
    if not title:
        return ("", 0, 0)
    m = re.search(r'(\d{4})\s*年第\s*([一二三四五六七八九十\d]+)\s*期', title)
    if not m:
        return ("", 0, 0)
    y = int(m.group(1))
    n = _cn_to_int(m.group(2))
    return (f'{y}.第{n}期', y, n)


# ── chip 状态写入（复用 dashboard `/tmp/gov-check-status/{city}.json` 契约） ──
CHECK_STATUS_FILE = os.path.join(STATUS_DIR, "ningxia.json")


def _write_check_status(*, chip_status, output, has_update,
                        site_period, site_year, site_month,
                        es_period, es_update_date):
    """复用重庆 _write_check_status 同结构：
      ok / update / error / pending
    """
    doc = {
        "city": "ningxia",
        "label": "宁夏",
        "status": chip_status,
        "output": output,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "has_update": has_update,
        "site_latest_period": site_period or "",
        "site_latest_year":   site_year or "",
        "site_latest_month":  site_month or "",
        "es_latest_period":   es_period or "",
        "es_latest_update_date": es_update_date or "",
    }
    try:
        os.makedirs(STATUS_DIR, exist_ok=True)
        with open(CHECK_STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        print(f"[+] check_status 写入: {CHECK_STATUS_FILE} status={chip_status}")
    except Exception as e:
        print(f"[!] 写 check_status 失败: {e}")


# ── main ───────────────────────────────────────────────────
def main():
    print("[i] 宁夏增量检测开始（browser 模式，绕过 CT2-WAAP）...")

    # 1. 加载配置 + 查 ES 最新
    with open(CONFIG_PATH, encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}
    es = Elasticsearch(cfg['es']['host'])
    ods_index = cfg['es']['ods_index']

    es_latest = ''
    es_latest_period = ''
    try:
        r = es.search(
            index=ods_index, size=1,
            sort=[{'update_date': 'desc'}],
            _source=['update_date', 'period'],
        )
        hits = r['hits']['hits']
        if hits:
            es_latest = hits[0]['_source'].get('update_date', '') or ''
            es_latest_period = hits[0]['_source'].get('period', '') or ''
    except Exception as e:
        print(f"[!] ES 查询失败: {e}")
        _write_check_status(
            chip_status='error', output=f"ES 查询失败: {e}", has_update=False,
            site_period='', site_year='', site_month='',
            es_period='', es_update_date='',
        )
        return

    # 2. browser tab
    tab_id = _check_browser_tab()
    if not tab_id:
        print("[!] browser tab 获取失败")
        _write_check_status(
            chip_status='error', output="browser 未打开（openclaw browser 不可用）",
            has_update=False,
            site_period='', site_year='', site_month='',
            es_period=es_latest_period, es_update_date=es_latest,
        )
        return
    print(f"[*] browser tab: {tab_id}")
    if not _focus_tab(tab_id):
        print("[!] 聚焦失败，继续尝试 JS 抽取（部分 openclaw 版本无需 focus 也可 evaluate）")

    # 给 WAF 挑战/列表渲染留 3 秒缓冲
    time.sleep(3)

    # 3. JS 抽期刊
    items = get_site_periods()
    print(f"[*] 抓取候选期刊数: {len(items)}")

    if not items:
        print("[!] 未抓到期刊条目（页面可能还在 WAF 验证/未渲染完成）")
        _write_check_status(
            chip_status='error', output="源站期刊列表为空（WAF/未渲染）",
            has_update=False,
            site_period='', site_year='', site_month='',
            es_period=es_latest_period, es_update_date=es_latest,
        )
        return

    # 4. 取"最新一期"
    first = items[0]
    site_title = first['title']
    site_date = _norm_date(first['date'])
    period_label, year, issue_num = parse_period_from_title(site_title)
    site_year = str(year) if year else ''
    site_month = (site_date[5:7] + '月') if site_date else ''

    print(f"[*] 源站最新: {site_title} (publish={site_date}, period={period_label})")
    print(f"[*] ES 最新:   {es_latest_period or '无'} (update_date={es_latest or '无'})")

    # 5. 比对
    new_data = False
    if site_date and es_latest:
        new_data = site_date > es_latest
    elif period_label and es_latest_period:
        m1 = re.match(r'(\d+)\.第(\d+)期', period_label)
        m2 = re.match(r'(\d+)\.第(\d+)期', es_latest_period)
        if m1 and m2:
            new_data = (int(m1.group(1)), int(m1.group(2))) > (int(m2.group(1)), int(m2.group(2)))

    chip_status = 'update' if new_data else 'ok'
    output = (
        f"源站 {period_label or site_title} (publish={site_date}) > ES {es_latest_period} (update={es_latest})"
        if new_data else
        f"无新数据（源站 == ES = {period_label or site_title}）"
    )
    print(f'[宁夏] {"🔔" if new_data else "✅"} {output}')

    _write_check_status(
        chip_status=chip_status, output=output, has_update=new_data,
        site_period=period_label, site_year=site_year, site_month=site_month,
        es_period=es_latest_period, es_update_date=es_latest,
    )


if __name__ == "__main__":
    main()

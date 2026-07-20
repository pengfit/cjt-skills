#!/usr/bin/env python3
import os
STATUS_DIR = os.environ.get("GOV_CHECK_STATUS_DIR", "/tmp/gov-check-status")
SUMMARY_DIR = os.environ.get("GOV_PRICE_SUMMARY_DIR", "/tmp/gov-price-summary")

import os
"""重庆 - 增量检测：对比 ES 最新入库日期 vs 源站最新月份

前置条件：browser 已打开目标页面
"""
import sys, os, json, time, re

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.yml")

import warnings
warnings.filterwarnings('ignore')
import yaml
from elasticsearch import Elasticsearch


def _run_cli(args, timeout=30):
    import subprocess
    r = subprocess.run(
        ["openclaw"] + args,
        capture_output=True, text=True, timeout=timeout,
        env={**os.environ}
    )
    return r.stdout, r.stderr


# openclaw CLI 有时在 stdout 里前置 doctor warnings 边框（框内嵌警告文案），
# 会污染 _eval_js 的首尾 strip。把这些装饰行过滤掉再剥 JSON-string 引号。
_DOCTOR_FRAME_CHARS = ('│', '┌', '┐', '└', '┘', '┤', '├', '┬', '┴', '┼',
                       '─', '╮', '╯', '╭', '╰', '◇')
_DOCTOR_KEYWORDS = ('Doctor', 'warnings', 'config-health', 'SQLite state',
                    'legacy config', 'Left')


def _strip_doctor_box(text: str) -> str:
    """丢弃 openclaw doctor warnings 框（边框字符行 + 关键词行）。"""
    cleaned = []
    for line in text.splitlines():
        if any(c in line for c in _DOCTOR_FRAME_CHARS):
            continue
        if any(kw in line for kw in _DOCTOR_KEYWORDS):
            continue
        cleaned.append(line)
    return '\n'.join(cleaned).strip()


def _eval_js(js_body: str) -> str:
    out, _ = _run_cli(["browser", "evaluate", "--fn", js_body])
    s = _strip_doctor_box(out).strip()
    if s.startswith('"') and s.endswith('"'):
        s = s[1:-1]
    return s.replace('\\"', '"')


def _check_browser_tab(tab_label="重庆市建设工程造价信息网") -> str | None:
    """查找已打开的 tab；没有则从 config.yml.site.url 主动打开，再返回新 tab id"""
    out, _ = _run_cli(["browser", "tabs"])
    for line in out.splitlines():
        if tab_label in line:
            m = re.search(r'\[?t(\d+)\]?', line)
            if m:
                return f"t{m.group(1)}"
    # tab 不存在 → 主动打开（适用于 cron 场景下无人预开 tab）
    site_url = "http://www.cqsgczjxx.org/Pages/CQZJW/priceInformation.aspx"
    try:
        with open(CONFIG_PATH, encoding='utf-8') as _f:
            site_url = (yaml.safe_load(_f) or {}).get("site", {}).get("url", site_url)
    except Exception:
        pass
    print(f"[*] 未找到已开 tab，主动打开: {site_url}")
    out, err = _run_cli(["browser", "open", site_url], timeout=60)
    if not out and err:
        print(f"[!] open 失败: {err.strip()[:200]}")
        return None
    # open 返回 JSON {targetId, tabId}；提取 tabId
    try:
        j = json.loads(out) if out.strip().startswith("{") else None
    except Exception:
        j = None
    if j and j.get("tabId"):
        return j["tabId"]
    # fallback: 重新 tabs
    import time as _t
    _t.sleep(2)
    out, _ = _run_cli(["browser", "tabs"])
    for line in out.splitlines():
        if tab_label in line:
            m = re.search(r'\[?t(\d+)\]?', line)
            if m:
                return f"t{m.group(1)}"
    return None


def _focus_tab(tab_id: str) -> bool:
    out, _ = _run_cli(["browser", "focus", tab_id])
    return "focused" in out.lower() or "ok" in out.lower()


def get_current_year_from_page() -> str | None:
    """提取下拉框当前选中的年份"""
    js = '''(function(){
var selects = document.querySelectorAll("select");
for(var i=0;i<selects.length;i++){
  var opts = selects[i].options;
  for(var j=0;j<opts.length;j++){
    if(opts[j].selected && opts[j].value){
      return opts[j].text.trim();
    }
  }
}
return null;
})()'''
    try:
        r = _eval_js(js)
        if r and r != "null":
            return r.strip()
    except Exception:
        pass
    return None


def get_month_options() -> list[str]:
    """提取页面上 class='month' 元素的所有月份文本"""
    js = '''(function(){
var els = document.querySelectorAll(".month");
var months = [];
for(var i=0;i<els.length;i++){
  var t = els[i].textContent.trim();
  if(t && /\\d+月/.test(t)) months.push(t);
}
return JSON.stringify(months);
})()'''
    try:
        raw = _eval_js(js)
        if raw and raw != "null":
            return json.loads(raw)
    except Exception:
        pass
    return []


def parse_month_to_period(year: str, month_str: str) -> str:
    """将 '04月' 或 '01月02月...05月' 转为最新 '2026-05-01'"""
    # class='month' 可能把多个月份连在一起，如 '01月02月03月04月05月'
    all_months = re.findall(r'(\d+)月', month_str)
    if not all_months:
        return ""
    # 取最大月份
    max_m = max(int(m) for m in all_months)
    return f"{year}-{max_m:02d}-01"


# ── check_status 写入（供 dashboard /scrape 顶部“定时检查状态”复用）──
# 复用现有机制：/api/stats/check-status 读 /tmp/gov-check-status/{city}.json
# 字段：city / label / status / output / time / has_update
# status 枚举：ok（无新数据）/ update（有更新）/ error（异常）/ pending（无记录）

CHECK_STATUS_DIR = os.environ.get("GOV_CHECK_STATUS_DIR", "/tmp/gov-check-status")
CHECK_STATUS_FILE = os.path.join(CHECK_STATUS_DIR, "chongqing.json")


def _write_check_status(site_period, site_year, site_month,
                        es_period, es_create_time, status, message):
    """写检查状态到 /tmp/gov-check-status/chongqing.json（复用 dashboard 现有多城 chip 机制）

    status 映射：
      ok          → status="ok",     has_update=False
      new_data    → status="update", has_update=True
      no_es_data  → status="error",  has_update=False
      no_site_data→ status="error",  has_update=False
      unknown     → status="error",  has_update=False
    """
    status_map = {
        "ok":            ("ok", False),
        "new_data":      ("update", True),
        "no_es_data":    ("error", False),
        "no_site_data":  ("error", False),
        "unknown":       ("error", False),
    }
    chip_status, has_update = status_map.get(status, ("error", False))

    doc = {
        "city": "chongqing",
        "label": "重庆",
        "status": chip_status,
        "output": message or "",
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "has_update": has_update,
        # 额外字段（API 透传，前端不使用但保留诊断信息）
        "site_latest_period": site_period or "",
        "site_latest_year":   site_year or "",
        "site_latest_month":  site_month or "",
        "es_latest_period":   es_period or "",
        "es_latest_create_time": es_create_time or "",
    }
    try:
        os.makedirs(CHECK_STATUS_DIR, exist_ok=True)
        with open(CHECK_STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        print(f"[+] check_status 写入: {CHECK_STATUS_FILE} status={chip_status}")
    except Exception as e:
        print(f"[!] 写 check_status 失败: {e}")


def main():
    print("[i] 重庆增量检测开始...")

    # 0. 加载配置
    with open(CONFIG_PATH, encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}
    es = Elasticsearch(cfg['es']['host'])
    ods_index = cfg['es']['index']

    # 1. 获取 ES 最新数据
    es_latest = ''
    es_latest_period = ''
    try:
        r = es.search(index=ods_index, size=1, sort=[{'create_time': 'desc'}],
                       _source=['create_time', 'period'])
        hits = r['hits']['hits']
        if hits:
            es_latest = hits[0]['_source'].get('create_time', '') or ''
            es_latest_period = hits[0]['_source'].get('period', '') or ''
    except Exception as e:
        print(f'[重庆] ES 查询失败: {e}')
        return

    # 2. 检查 browser
    tab_id = _check_browser_tab()
    if not tab_id:
        print("[!] browser 未打开")
        print(f'[重庆] ES 最新入库: {es_latest or "无"} ({es_latest_period})')
        return

    print(f"[*] browser tab: {tab_id}")
    if not _focus_tab(tab_id):
        print("[!] 聚焦失败")
        return
    time.sleep(1)

    # 3. 点击'材料信息价'
    click_js = '''(function(){
var navs = document.querySelectorAll(".priceNav");
for(var i=0;i<navs.length;i++){
  if(navs[i].innerText.trim()==="材料信息价"){navs[i].click();return"OK";}
}
return"NOT_FOUND";
})()'''
    out, _ = _run_cli(["browser", "evaluate", "--fn", click_js])
    if "OK" not in out:
        print("[!] 未找到'材料信息价'标签页")
        return
    time.sleep(2)

    # 4. 提取年份
    current_year = get_current_year_from_page()
    if not current_year:
        print("[!] 无法提取年份")
        return

    # 5. 提取 class='month' 的月份列表
    months = get_month_options()

    print(f'[*] 年份: {current_year}')
    print(f'[*] 可用月份: {months}')

    # 6. 取最大月份作为源站最新
    site_latest_period = ''
    site_latest_month = ''
    if months:
        # months 数组中每个元素可能是连在一起的 '01月02月...05月'
        site_latest_period = parse_month_to_period(current_year, months[0] if months else '')
        if site_latest_period:
            site_latest_month = site_latest_period[5:7] + '月'

    print(f'[重庆] 源站最新: {current_year}年{site_latest_month} ({site_latest_period})')
    print(f'[重庆] ES 最新:   {es_latest_period or "无"} (入库 {str(es_latest)[:19] if es_latest else "无"})')

    # 7. 对比
    status = "unknown"
    message = ""
    if site_latest_period:
        if not es_latest_period:
            print(f'[重庆] 🔔 ES 无数据，需首次同步')
            status = "no_es_data"
            message = f"ES 无数据，需首次同步（源站 {site_latest_period}）"
        elif site_latest_period > es_latest_period:
            print(f'[重庆] 🔔 有更新！源站 {site_latest_period} > ES {es_latest_period}')
            status = "new_data"
            message = f"源站 {site_latest_period} > ES {es_latest_period}，需同步"
        else:
            print(f'[重庆] ✅ 无新数据')
            status = "ok"
            message = f"无新数据（源站 == ES = {site_latest_period}）"
    else:
        print(f'[重庆] ⚠️ 无法解析源站月份')
        status = "no_site_data"
        message = "无法解析源站月份"

    # 8. 写 check_status（供 dashboard /scrape 顶部的「定时检查状态」复用）
    _write_check_status(
        site_latest_period, current_year or '', site_latest_month,
        es_latest_period, es_latest,
        status, message,
    )


if __name__ == "__main__":
    main()

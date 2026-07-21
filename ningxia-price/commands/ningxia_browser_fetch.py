"""宁夏 sync 浏览器 fetcher (v1, 2026-07-21)

源站 jst.nx.gov.cn 启用了 CT2-WAAP（知道创宇）拦截 HTTP requests（412 + 滑块挑战）。
仿 chongqing-price/commands/check.py 思路：用 `openclaw browser` 替代 requests，
让浏览器（已带 cookie / JS 挑战已通过）抓列表 + 详情页。

接口签名与 sync_v3_legacy.fetch_all_periods / fetch_detail_pdf 完全相同，
让 sync_legacy.py 仅做 import 转发，collector / preview 一行不动。

约束与取舍：
- 依赖浏览器里有 jst.nx.gov.cn 的 tab；若没有由 `_open_or_focus_tab` 自动 open。
- WAF 挑战：首次 navigate 可能落在 "请稍候…" 页，函数会自动 sleep + retry。
- 分页：按 cfg['site']['list_pages'] 依次 navigate 到列表页，JS 抽取后聚合 + dedupe。
- PDF 下载：保留 utils.download_file 直连（PDF 通常不在 WAF 后）。
  若以后发现 PDF 静态资源也被 WAF 拦，加 fetch_pdf_browser() 重定向即可。
"""

import os
import re
import sys
import json
import time
import subprocess


# ── openclaw CLI 封装 ─────────────────────────────────────────
def _run_cli(args, timeout=30):
    return subprocess.run(
        ["openclaw"] + list(args),
        capture_output=True, text=True, timeout=timeout,
        env={**os.environ},
    )


# openclaw doctor warning 框会污染 stdout，过滤掉（与 check.py 同构）。
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
    if s.startswith('"') and s.endswith('"'):
        s = s[1:-1]
    return s.replace('\\"', '"').replace('\\\\"', '"')


# ── tab 管理 ─────────────────────────────────────────────────
SITE_URL = "https://jst.nx.gov.cn/ztzl/gczj/zjtt/index.html"
TAB_LABEL = "宁夏"
# CT2-WAAP 挑战页特征：滑块元素 / 等待文案
WAF_SELECTORS = '.puzzle-vcode, #msg, .ctct-slider-canvas'
WAF_TITLE_KEY = '请稍候'


def ensure_browser_running() -> bool:
    """确保 openclaw browser 已 running；未跑则自动 start。

    Cron / 初始 session 可能没把 browser 拉起，后续 navigate / open 会被
    gateway 拒（'browser navigation blocked by policy'）。这里 auto-start。

    Returns:
        True=浏览器已 running；False=启动失败。
    """
    r, _ = _run_cli(["browser", "status"])
    if r and "running: true" in r:
        return True
    print("[*] browser 未启动，自动 openclaw browser start...")
    s, _ = _run_cli(["browser", "start"])
    time.sleep(2)
    r, _ = _run_cli(["browser", "status"])
    if not (r and "running: true" in r):
        print(f"[!] browser start 失败: start={(s or '').strip()[:200]}")
        return False
    return True


def _focus_tab_by_id(tab_id: str) -> bool:
    out, _ = _run_cli(["browser", "focus", tab_id], timeout=15)
    return "focused" in out.lower() or "ok" in out.lower()


def _open_or_focus_tab() -> bool:
    """确保有 jst.nx.gov.cn 的 tab 并聚焦。自动 start browser。"""
    if not ensure_browser_running():
        return False
    out, _ = _run_cli(["browser", "tabs"])
    for line in (out or '').splitlines():
        if TAB_LABEL in line:
            m = re.search(r'\[?t(\d+)\]?', line)
            if m:
                return _focus_tab_by_id(f"t{m.group(1)}")
    # 没有就 open
    print(f"[*] browser tab 未找到，主动 open: {SITE_URL}")
    r = _run_cli(["browser", "open", SITE_URL], timeout=60)
    if not r.stdout and r.stderr:
        print(f"[!] open 失败: {r.stderr.strip()[:200]}")
        return False
    time.sleep(3)
    # 再 focus
    out, _ = _run_cli(["browser", "tabs"])
    for line in (out or '').splitlines():
        if TAB_LABEL in line:
            m = re.search(r'\[?t(\d+)\]?', line)
            if m:
                return _focus_tab_by_id(f"t{m.group(1)}")
    return False


def _is_waf_challenge() -> bool:
    """当前页面是否还在 CT2-WAAP 挑战页。"""
    js = (
        "(function(){"
        f" var el = document.querySelector('{WAF_SELECTORS}');"
        f" var t = (document.title || '');"
        " return (el || t.indexOf('" + WAF_TITLE_KEY + "') >= 0) ? 'true' : 'false';"
        "})()"
    )
    try:
        r = _eval_js(js, timeout=15)
        return 'true' in r.lower()
    except Exception:
        return False


def _has_selector(selector: str) -> bool:
    js = (
        "(function(){"
        f" return !!document.querySelector('{selector}') ? 'true' : 'false';"
        "})()"
    )
    try:
        r = _eval_js(js, timeout=10)
        return 'true' in r.lower()
    except Exception:
        return False


def _navigate(url: str, wait_selector: str = 'a', retries: int = 3, settle_wait: int = 2) -> bool:
    """在当前 tab 里 navigate 到 URL，等目标选择器出现。遇 WAF 自动 sleep+retry。

    Args:
        url: 目标 URL
        wait_selector: 期望出现的 CSS 选择器；空字符串=不等待
        retries: navigate 失败重试次数（含 WAF 挑战场景）
        settle_wait: 每次 navigate 后的初始等待秒数

    Returns:
        True=成功到目标页面，False=最终仍未通过 WAF / 渲染失败
    """
    if not _open_or_focus_tab():
        return False
    last_err = ''
    for i in range(retries):
        r = _run_cli(["browser", "navigate", url], timeout=60)
        if not r.stdout and r.stderr:
            last_err = r.stderr.strip()[:200]
            time.sleep(settle_wait + i)
            continue
        time.sleep(settle_wait + i)
        if _is_waf_challenge():
            time.sleep(3 + i * 2)
            continue
        if wait_selector:
            ok = False
            for _ in range(8):
                if _has_selector(wait_selector):
                    ok = True
                    break
                time.sleep(1)
            if not ok:
                continue
        return True
    if last_err:
        print(f"  [!] navigate 最终失败: {last_err}")
    return False


# ── 文本/日期规范化 ──────────────────────────────────────────
def _norm_date(d: str) -> str:
    """'2026年5月18日' / '2026-05-18' / '2026/5/18' 统一为 YYYY-MM-DD"""
    if not d:
        return ''
    m = re.search(r'(\d{4})\D+(\d{1,2})\D+(\d{1,2})', d)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ''


# ── 主要对外函数：fetch_all_periods ───────────────────────────
def _extract_list_items_js() -> str:
    return r'''(function(){
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
return JSON.stringify(out.slice(0, 60));
})()'''


def _extract_list_items() -> list[dict]:
    """在当前 tab 里抓候选期刊条目。"""
    try:
        raw = _eval_js(_extract_list_items_js(), timeout=30)
        if raw and raw != "null":
            return json.loads(raw)
    except Exception as e:
        print(f"  [!] JS 抽取失败: {e}")
    return []


def fetch_all_periods(cfg: dict) -> list[dict]:
    """抓取所有期（首页 + 分页）。返回 [{title, publish_date, detail_url}, ...]。

    与 sync_v3_legacy.fetch_all_periods 同接口，便于平替。
    """
    site = cfg['site']
    base = site['base_url']
    all_items: list[dict] = []
    for page in range(1, site['list_pages'] + 1):
        if page == 1:
            url = base + site['list_path']
        else:
            url = base + site['list_page_pattern'].format(n=page)
        if not _navigate(url, wait_selector='a'):
            print(f'  [list-browser] page {page}: navigate 失败，跳过')
            continue
        items = _extract_list_items()
        print(f'  [list-browser] page {page}: {len(items)} 期')
        all_items.extend(items)
    # 去重 + 字段映射（href → detail_url）
    seen = set()
    uniq: list[dict] = []
    for it in all_items:
        u = it['href']
        if u in seen:
            continue
        seen.add(u)
        uniq.append({
            'title': it['title'],
            'publish_date': _norm_date(it.get('date', '')),
            'detail_url': u,
        })
    return uniq


# ── 主要对外函数：fetch_detail_pdf ────────────────────────────
_DETAIL_PDF_JS = r'''(function(){
var a = document.querySelector('a[href$=".pdf"]');
if (a) {
  return JSON.stringify({u: a.href, t: (a.innerText||a.textContent||"").trim()});
}
var scripts = document.querySelectorAll('script');
var txt = '';
for (var i=0;i<scripts.length;i++){ txt += scripts[i].innerHTML + '\n'; }
var m = txt.match(/var\s+params\s*=\s*["']([^"']+\.pdf)["']/);
if (m) {
  var u = m[1];
  if (!/^https?:/.test(u)) {
    try { u = new URL(u, location.href).href; } catch (e) {}
  }
  return JSON.stringify({u: u, t: ''});
}
return JSON.stringify({u: '', t: ''});
})()'''


def fetch_detail_pdf(cfg: dict, detail_url: str) -> tuple[str, str | None, str | None]:
    """浏览器访问详情页，提取 PDF URL + 标题。

    Returns:
        (title, pdf_url, pdf_link_text)。无 PDF 时 pdf_url/pdf_link_text 为 None。
    """
    if not _navigate(detail_url, wait_selector='script,a'):
        return ('', None, None)

    try:
        title = _eval_js("document.title || ''", timeout=15) or ''
    except Exception:
        title = ''

    try:
        raw = _eval_js(_DETAIL_PDF_JS, timeout=20)
        if not raw or raw == "null":
            return (title, None, None)
        d = json.loads(raw)
        u = d.get('u') or ''
        t = d.get('t') or ''
        if not u:
            return (title, None, None)
        return (title, u, t)
    except Exception as e:
        print(f"  [!] 详情 PDF 解析失败: {e}")
        return (title, None, None)


# ── self-test（手动 `python3 -m ningxia_browser_fetch` 跑通） ─────
if __name__ == "__main__":
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    if SCRIPT_DIR not in sys.path:
        sys.path.insert(0, SCRIPT_DIR)
    from utils import load_config

    cfg = load_config()
    print(f"[*] 抓取列表（browser）...")
    items = fetch_all_periods(cfg)
    print(f"[*] 共 {len(items)} 期")
    for it in items[:5]:
        print(f"  - {it['title'][:40]:40s} {it['publish_date']:12s} {it['detail_url']}")
    if items:
        first = items[0]
        print(f"\n[*] 抓详情: {first['detail_url']}")
        title, pdf_url, pdf_link = fetch_detail_pdf(cfg, first['detail_url'])
        print(f"  title: {title}")
        print(f"  pdf:   {pdf_url}")
        print(f"  link:  {pdf_link}")

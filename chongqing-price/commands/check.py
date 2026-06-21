#!/usr/bin/env python3
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


def _eval_js(js_body: str) -> str:
    out, _ = _run_cli(["browser", "evaluate", "--fn", js_body])
    s = out.strip()
    if s.startswith('"') and s.endswith('"'):
        s = s[1:-1]
    return s.replace('\\"', '"')


def _check_browser_tab(tab_label="重庆市建设工程造价信息网") -> str | None:
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
    if site_latest_period:
        if not es_latest_period:
            print(f'[重庆] 🔔 ES 无数据，需首次同步')
        elif site_latest_period > es_latest_period:
            print(f'[重庆] 🔔 有更新！源站 {site_latest_period} > ES {es_latest_period}')
        else:
            print(f'[重庆] ✅ 无新数据')
    else:
        print(f'[重庆] ⚠️ 无法解析源站月份')


if __name__ == "__main__":
    main()

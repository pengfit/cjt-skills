#!/usr/bin/env python3
"""ES 写入工具 - 被 browser 侧 / agent 调用

用法:
  python3 write_es.py init                              # 初始化 ES 索引
  python3 write_es.py write <run_id> <county> <period> <result_json>
  python3 write_es.py progress <run_id> <county> <period> <page> <total_pages> <docs_written> <status> [error] [duration]
  python3 write_es.py summary <run_id> <total_counties> <completed> <total_docs> <duration_sec>
  python3 write_es.py sync [--tab-id <id>] [--reset]    # 完整同步流程（CLI browser + ES）
"""
import sys, os, json, time, hashlib, re, signal, argparse, subprocess, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
warnings.filterwarnings('ignore')
import requests
from datetime import datetime

import yaml as _yaml

# ── 复用 gov_price_etl 通用层（区间价解析 / 价格有效性） ─────────────
# 与 dashboard 的 ETL_PROJECT_ROOT 模式一致：
# 让 chongqing-price 能直接用 gov_price_etl.parse_price 的权威实现，
# 避免两边维护同一份正则（_parse_interval_price 在 chongqing v3 + 通用版同时改易漏）。
_ETL_PROJECT_ROOT = os.path.expanduser("~/.openclaw/workspace/skills/gov-price-etl")
if os.path.isdir(_ETL_PROJECT_ROOT) and _ETL_PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _ETL_PROJECT_ROOT)
try:
    from gov_price_etl.parse_price import parse_interval_price as _parse_interval_price
    from gov_price_etl.indexer import ensure_progress_index as _ensure_progress_index
except ImportError as _e:
    # 硬约束：通用层必须可用。如果将来 chongqing 部署到没有 etl skill 的环境，
    # 在这里显式报错，不要默默走本地 fallback 留下隐患。
    raise ImportError(
        f"chongqing-price 依赖 gov_price_etl.parse_price，"
        f"未在 {_ETL_PROJECT_ROOT} 找到：{_e}。请确认 gov-price-etl skill 已部署。"
    )

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.yml')

def _load_config():
    with open(_CONFIG_PATH, encoding='utf-8') as f:
        return _yaml.safe_load(f) or {}

_es_cfg = _load_config().get('es', {})
ES_HOST = _es_cfg.get('host', 'http://localhost:59200')
ES_INDEX = _es_cfg.get('index', 'ods_material_chongqing_price')
PROGRESS_INDEX = _es_cfg.get('progress_index', 'ods_chongqing_price_progress')
RUN_ID_PREFIX = "cq_run"

ALL_COUNTIES_DISTRICT = [
    "主城区", "万州区", "涪陵区", "黔江区", "长寿区", "江津区", "合川区",
    "永川区", "南川区", "梁平区", "城口县", "丰都县", "垫江县", "忠县",
    "开州区", "云阳县", "奉节县", "巫山县", "巫溪县", "石柱县", "秀山县",
    "酉阳县", "大足区", "綦江区", "万盛经开区", "双桥经开区", "铜梁区",
    "璧山区", "彭水县1", "彭水县2", "彭水县3", "荣昌区1", "荣昌区2",
    "潼南区", "武隆区",
]

ALL_COUNTIES_MORTAR = [
    "主城区", "永川区", "綦江区", "璧山区",
]

SOURCE_CONFIG = {
    "district": {
        "div_id": "gqxdfclDiv",
        "counties": ALL_COUNTIES_DISTRICT,
        "counties_key": "ALL_COUNTIES",
        "label": "区县主要材料信息价",
        "item_label": "区县材料价格",
        "onclick": "loadrgjgXX('{div_id}',1,0,'{label}')",
    },
    "mortar": {
        "div_id": "ybsjDiv",
        "counties": ALL_COUNTIES_MORTAR,
        "counties_key": "ALL_COUNTIES_MORTAR",
        "label": "预拌砂浆信息价",
        "item_label": "预拌砂浆价格",
        "onclick": "loadrgjgXX('{div_id}',1,0,'{label}')",
    },
    "citywide": {
        "div_id": "zyclDiv",
        "counties": ["主城区"],  # 无区县选择，左侧类目选择
        "counties_key": "ALL_COUNTIES_CITYWIDE",
        "categories": ["建安工程材料", "园林绿化工程材料", "绿色、节能建筑工程材料", "装配式建筑工程成品构件", "城市轨道交通工程材料"],
        "label": "重庆市材料信息价",
        "item_label": "重庆市材料信息价",
        "onclick": "loadJJ('{div_id}','1')",
    },
}

ALL_COUNTIES = ALL_COUNTIES_DISTRICT

PROGRESS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".chongqing_sync_progress.json"
)


def _doc_id(breed, spec, period, price, tax_price, county):
    """原价 _id，保留兼容：用于旧数据或单值场景。

    v4 (2026-07-02) ：新增 _doc_id_v4 用 price_min/price_max 作为哈希因子。
    区间价场景里价不同 → _id 不同，避免旧 _id（基于 0）覆盖。
    """
    raw = f"{breed}_{spec}_{period}_{price}_{tax_price}_{county}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _doc_id_v4(breed, spec, period, price_min, price_max, price_range, county):
    """v4: 用区间边界作哈希因子。

    区分单值与区间：间区连 is_range 一起进哈希。
    """
    raw = f"{breed}_{spec}_{period}_{price_min}_{price_max}_{price_range}_{county}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _parse_period(s: str) -> str:
    m = re.search(r"(\d{4})年(\d{1,2})月", s or "")
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(2)}-01"
    return ""


def _load_gateway_token():
    cfg_path = os.path.expanduser("~/.openclaw/openclaw.json")
    try:
        with open(cfg_path) as f:
            cfg = json.load(f)
        return cfg.get("gateway", {}).get("auth", {}).get("token", "")
    except Exception:
        return ""


# ─── 索引初始化 ───────────────────────────────────────────────

def _ensure_index(idx, mapping):
    r = requests.head(f"{ES_HOST}/{idx}", timeout=10, verify=False)
    if r.status_code == 200:
        return
    r2 = requests.put(f"{ES_HOST}/{idx}", json=mapping, timeout=15, verify=False)
    if r2.status_code not in (200, 201):
        raise RuntimeError(f"创建索引 {idx} 失败: {r2.status_code}")


def cmd_init():
    _ensure_index(ES_INDEX, {
        "mappings": {
            "properties": {
                "breed":       {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
                "spec":        {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
                "unit":        {"type": "keyword"},
                "price":       {"type": "float"},
                "tax_price":   {"type": "float"},
                "is_tax":      {"type": "keyword"},
                "period":      {"type": "keyword"},
                "period_start":{"type": "date", "format": "yyyy-MM-dd"},
                "period_end":  {"type": "date", "format": "yyyy-MM-dd"},
                "period_days": {"type": "integer"},
                "province":    {"type": "keyword"},
                "city":        {"type": "keyword"},
                "county":      {"type": "keyword"},
                "area_code":   {"type": "keyword"},
                "update_date": {"type": "date", "format": "yyyy-MM-dd"},
                "create_time": {"type": "date", "format": "yyyy-MM-dd HH:mm:ss||yyyy-MM-dd||strict_date_optional_time"}
            }
        }
    })
    # v0.6 (2026-07-02) ：委托到 gov_price_etl.indexer.ensure_progress_index。
    # 已存在索引走 noop 保护（dynamic=strict 不允许改字段类型，避免冲突）。
    _ensure_progress_index(ES_HOST, PROGRESS_INDEX)
    print("[+] 索引初始化完成")


# ─── ES 写入（write / progress / summary）────────────────────

def cmd_write(run_id, county, period, result_json):
    try:
        data = json.loads(result_json)
    except Exception:
        print(f"[!] JSON 解析失败")
        return 0

    rows = data.get("rows", [])
    if not rows:
        print(f"[i] {county}: 无数据")
        return 0

    parsed = _parse_period(data.get("period", ""))
    actual_period = parsed if parsed else _parse_period(period)
    if not actual_period:
        actual_period = time.strftime("%Y-%m-%d")

    docs = []
    for row in rows:
        if len(row) < 6:
            continue
        breed = row[1] if len(row) > 1 else ""
        spec = row[2] if len(row) > 2 else ""
        unit = row[3] if len(row) > 3 else ""
        tax_str = row[4] if len(row) > 4 else ""
        price_str = row[5] if len(row) > 5 else ""
        if not breed or breed == "材料名称":
            continue
        try:
            tax_val = float(re.sub(r"[￥,，元\-\s]", "", tax_str)) if tax_str else 0.0
            price_val = float(re.sub(r"[￥,，元\-\s]", "", price_str)) if price_str else 0.0
        except Exception:
            continue
        docs.append({
            "_id": _doc_id(breed, spec or "", actual_period, str(price_val), str(tax_val), county),
            "breed": breed,
            "spec": spec or "",
            "unit": unit or "",
            "price": price_val,
            "tax_price": tax_val,
            "is_tax": "含税" if tax_val > 0 else "不含税",
            "period": actual_period,
            "province": "重庆",
            "city": county,
            "county": county,
            "area_code": county,
            "update_date": actual_period,
            "create_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        })

    if not docs:
        return 0

    bulk = ""
    for doc in docs:
        did = doc.pop("_id")
        bulk += json.dumps({"index": {"_index": ES_INDEX, "_id": did}}, ensure_ascii=False) + "\n"
        bulk += json.dumps(doc, ensure_ascii=False) + "\n"
    resp = requests.post(f"{ES_HOST}/_bulk",
        data=bulk.encode("utf-8"),
        headers={"Content-Type": "application/x-ndjson"},
        timeout=60, verify=False)
    if resp.status_code in (200, 201):
        n = sum(
            1 for it in resp.json().get("items", [])
            if it.get("index", {}).get("result") in ("created", "updated")
        )
        print(f"[+] {county}: 写入 {n} 条")
        return n
    print(f"[!] {county}: 写入失败 {resp.status_code}")
    return 0


def cmd_progress(run_id, county, period, current_page, total_pages, docs_written, status, error="", duration=0, source="district"):
    label_map = {"district": "区县材料", "mortar": "预拌砂浆", "citywide": "重庆材料信息价"}
    area_label = f"{label_map.get(source, source)}-{county}"
    doc = {
        "run_id": run_id,
        "status": status,
        "area": area_label,
        "period": period,
        "current_page": current_page,
        "total_pages": total_pages,
        "docs_written": docs_written,
        "percent": 100.0 if status in ("completed", "error") else (
            round(current_page / total_pages * 100, 1) if total_pages else 0
        ),
        "duration_sec": round(duration, 1),
        "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "error": error,
    }
    r = requests.put(
        # v0.6 _id 标准化：__ 分隔 source/county/period（兼容老 run_id_county 文档）
        f"{ES_HOST}/{PROGRESS_INDEX}/_doc/{run_id}__{source}__{county}__{period}",
        json=doc, timeout=15, verify=False
    )
    if r.status_code in (200, 201):
        print(f"[+] progress: {county} {status}")
    return r.status_code in (200, 201)


def cmd_summary(run_id, target_period, total_counties, completed, total_docs, duration_sec):
    doc = {
        "run_id": run_id,
        "status": "completed",
        "area": "全部完成",
        "period": target_period,
        "current_page": completed,
        "total_pages": total_counties,
        "docs_written": total_docs,
        "percent": round(completed / total_counties * 100, 1) if total_counties else 0,
        "duration_sec": round(duration_sec, 1),
        "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "error": "",
    }
    # _id 含 period:跨月份多个 summary 互不覆盖
    # v0.6 _id 标准化：__summary__ 分隔符
    _id = f"{run_id}__summary__{target_period}"
    r = requests.put(
        f"{ES_HOST}/{PROGRESS_INDEX}/_doc/{_id}",
        json=doc, timeout=15, verify=False
    )
    if r.status_code in (200, 201):
        print(f"[+] summary: {completed}/{total_counties} counties, {total_docs} docs, {duration_sec}s")
    return r.status_code in (200, 201)


# ─── 浏览器交互（CLI 方式）────────────────────────────────────

def _run_cli(args, timeout=35):
    token = _load_gateway_token()
    env = os.environ.copy()
    env["OPENCLAW_GATEWAY_TOKEN"] = token
    r = subprocess.run(
        ["openclaw"] + args,
        capture_output=True, text=True, timeout=timeout, env=env
    )
    return r.stdout, r.stderr


def _focus_tab(tab_id):
    out, _ = _run_cli(["browser", "focus", tab_id])
    return "focused tab" in out


def _eval_js(js_body: str) -> str:
    out, _ = _run_cli(["browser", "evaluate", "--fn", js_body])
    s = out.strip()
    # CLI output may be wrapped in a table box. Find the actual JSON string.
    # The JSON result is a double-quoted string, possibly with escaped inner quotes.
    # Look for the first '"' that starts a JSON object/array, and unescape accordingly.
    # Find the JSON-stringified result between the table border lines.
    lines = s.split('\n')
    # The actual result is typically the last non-empty line that starts with a quote
    result_line = None
    for line in reversed(lines):
        stripped = line.strip()
        if stripped.startswith('"') and stripped.endswith('"'):
            result_line = stripped
            break
    if not result_line:
        return s  # fallback: return as-is
    result_line = result_line[1:-1]  # strip outer quotes
    result_line = result_line.replace('\\"', '"')  # unescape embedded quotes
    return result_line


def _click_material_price_tab():
    """点击'材料信息价'标签页"""
    js = '''(function(){
var navs = document.querySelectorAll(".priceNav");
for(var i=0;i<navs.length;i++){
  if(navs[i].innerText.trim()==="材料信息价"){navs[i].click();return"OK";}
}
return"NOT_FOUND";
})()'''
    return "OK" in _eval_js(js)


def _click_search():
    js = """(function(){
var btns=document.querySelectorAll('button');
for(var i=0;i<btns.length;i++){
  if(btns[i].innerText.trim()==='搜索'){btns[i].click();return'OK:search';}
}
return'NOT_FOUND';
})()"""
    return "OK" in _eval_js(js)


def _click_source_tab(source: str):
    """点击材料信息价下的子tab：district / mortar / citywide"""
    cfg = SOURCE_CONFIG.get(source)
    if not cfg:
        return False
    div_id = cfg["div_id"]
    js = f'''(function(){{
var spans = document.querySelectorAll('#CLJGXX .slectMenu span');
for(var i=0;i<spans.length;i++){{
  if(spans[i].getAttribute('showdiv')==='{div_id}'){{
    spans[i].click();
    return'OK:'+'{div_id}';
  }}
}}
return'NOT_FOUND';
}})()'''
    return 'OK' in _eval_js(js)

def _click_county(name: str, source: str = "district"):
    cfg = SOURCE_CONFIG.get(source, {})
    div_id = cfg.get("div_id", "gqxdfclDiv")
    label = cfg.get("item_label", "区县材料价格")

    def _do_click():
        # 关键：jQuery 的 trigger('click') 才能触发 jQuery 绑定的事件处理器
        # 原生 span.click() 不会触发 jQuery 的 .click() 事件
        js = f'''(function(){{
var spans = document.querySelectorAll('#{div_id} .locality span');
for(var i=0;i<spans.length;i++){{
  if(spans[i].innerText.trim() === "{name}"){{
    if(window.$ && $.fn && typeof $.fn.jquery === "string"){{
      $(spans[i]).trigger("click");
    }} else {{
      spans[i].click();
    }}
    return "OK:"+'{name}';
  }}
}}
return "NOT_FOUND:"+'{name}';
}})()'''
        return _eval_js(js)

    result = _do_click()
    if not result.startswith("OK:"):
        return False

    # 验证 heading 中的区县名是否匹配（最多等 10 秒）
    # district: "2026年01月 重庆市{city}区县材料价格"
    # mortar: "2026年01月 重庆市{city}预拌砂浆价格"
    if source == "mortar":
        heading_pat = '重庆市(.+?)预拌砂浆价格'
    elif source == "citywide":
        heading_pat = '重庆市材料信息价'
    else:
        heading_pat = '重庆市(.+?)区县材料价格'

    for attempt in range(5):
        time.sleep(2)
        js_verify = f'''(function(){{
  var ps = document.querySelectorAll('#{div_id} p.title');
  for(var i=0;i<ps.length;i++){{
    var t = ps[i].innerText.trim();
    var m = t.match('{heading_pat}');
    if(m) return m[1];
    if(t.includes('重庆市')) return t;
  }}
  return '';
}})()'''
        current = _eval_js(js_verify).strip()
        if current == name:
            return True
    return current == name

def _click_search(source: str = "district"):
    """点击搜索按钮"""
    cfg = SOURCE_CONFIG.get(source, {})
    div_id = cfg.get("div_id", "gqxdfclDiv")
    label = cfg.get("item_label", "")
    onclick_tpl = cfg.get("onclick", "loadrgjgXX('{div_id}',1,0,'{label}')")
    onclick_str = onclick_tpl.replace('{div_id}', div_id).replace('{label}', label)
    js = f'''(function(){{
var btns = document.querySelectorAll('#{div_id} button');
for(var i=0;i<btns.length;i++){{
  if(btns[i].innerText.trim()==='搜索'){{btns[i].click();return'OK:search';}}
}}
return'NOT_FOUND';
}})()'''
    return 'OK:' in _eval_js(js)

def _select_month(month_num: str, source: str = "district"):
    """选中目标月份，month_num 传入 04（自动拼接"月"）"""
    cfg = SOURCE_CONFIG.get(source, {})
    div_id = cfg.get("div_id", "gqxdfclDiv")
    month_val = f"{month_num}月"
    js = f'''(function(){{
var sels = document.querySelectorAll('#{div_id} select.month');
var target = null;
for(var i=0;i<sels.length;i++){{
  if(sels[i].options.length >= 4){{ target = sels[i]; break; }}
}}
if(!target) {{
  for(var i=0;i<sels.length;i++){{
    if(sels[i].options.length > 1){{ target = sels[i]; break; }}
  }}
}}
if(!target) return 'NO_MONTH_SELECT';
var found = false;
for(var j=0;j<target.options.length;j++){{
  if(target.options[j].value === '{month_val}' || target.options[j].innerText === '{month_val}'){{
    target.options[j].selected = true;
    found = true;
    break;
  }}
}}
var evt = new Event('change', {{bubbles: true}});
    target.dispatchEvent(evt);
    // citywide 需要额外触发搜索按钮的 onclick 才发 AJAX
    var btns = document.querySelectorAll('#{div_id} button');
    for(var i=0;i<btns.length;i++){{if(btns[i].innerText.trim()==='搜索'){{btns[i].click();break;}}}}
    return found ? 'OK:{month_val}' : 'MONTH_NOT_FOUND:{month_val}';
}})()'''
    return 'OK' in _eval_js(js)

def _click_category(name: str, div_id: str = "zyclDiv") -> bool:
    """点击 citywide 的分类 tab（建安工程材料、园林绿化工程材料 等）"""
    js = f'''(function(){{
var spans = document.querySelectorAll('#{div_id} span');
for(var i=0;i<spans.length;i++){{
  if(spans[i].innerText.trim() === "{name}"){{
    if(window.$ && $.fn && typeof $.fn.jquery === "string"){{
      $(spans[i]).trigger("click");
    }} else {{
      spans[i].click();
    }}
    return "OK:"+ "{name}";
  }}
}}
return "NOT_FOUND:"+ "{name}";
}})()'''
    return 'OK' in _eval_js(js)


def _click_next(source: str = "district"):
    """点击下一页（通用，通过 div_id 定位）"""
    cfg = SOURCE_CONFIG.get(source, {})
    div_id = cfg.get("div_id", "gqxdfclDiv")
    js = f'''(function(){{
var spans = document.querySelectorAll('#{div_id} span.pageBtn');
for(var i=0;i<spans.length;i++){{
  if(spans[i].innerText.trim()==='下一页'){{spans[i].click();return'OK:next';}}
}}
return'NO_NEXT';
}})()'''
    return 'OK' in _eval_js(js)

def _extract_page(source: str = "district") -> dict:
    """提取当前页数据（通用，通过 div_id 定位）"""
    cfg = SOURCE_CONFIG.get(source, {})
    div_id = cfg.get("div_id", "gqxdfclDiv")
    js = f'''(function(){{
var tab = document.querySelector('#{div_id}');
if(!tab) return JSON.stringify({{err:'no tab'}});
var tbody = tab.querySelector('tbody.tbody');
if(!tbody) return JSON.stringify({{err:'no tbody'}});
var rows = [];
tbody.querySelectorAll('tr').forEach(function(tr){{
  var cells = tr.querySelectorAll('td');
  if(cells.length >= 6) rows.push(Array.from(cells).map(function(c){{return c.innerText.trim();}}));
}});
var bt = document.body.innerText;
var tp = bt.match(/共\s*(\d+)\s*页/);
var cp = bt.match(/第(\d+)\s*页/);
var nextSpans = document.querySelectorAll('#{div_id} span.pageBtn');
var nextBtn = null;
for(var i=0;i<nextSpans.length;i++){{if(nextSpans[i].innerText.trim()==='下一页'){{nextBtn=nextSpans[i];break;}}}}
var isLastPage = tp && cp && parseInt(tp[1]) === parseInt(cp[1]);
var hasNext = nextBtn && !nextBtn.classList.contains('pageBtnActive');
return JSON.stringify({{rows:rows,totalPages:tp?parseInt(tp[1]):1,currentPage:cp?parseInt(cp[1]):1,hasNext:hasNext && !isLastPage}});
}})()'''
    try:
        raw = _eval_js(js)
        return json.loads(raw)
    except Exception:
        return {"rows": [], "totalPages": 1, "currentPage": 1, "hasNext": False}

def _get_counties(source: str):
    """获取指定 source 对应的区县列表"""
    cfg = SOURCE_CONFIG.get(source, {})
    return cfg.get("counties", [])


# ─── 进度文件 ────────────────────────────────────────────────

def _load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"done": [], "run_id": ""}


def _save_progress(done, run_id):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "done": done, "run_id": run_id,
            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }, f, ensure_ascii=False, indent=2)


def _reset_progress():
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)


# ─── 同步主流程 ─────────────────────────────────────────────

def cmd_sync(args):
    tab_id = args.tab_id
    reset = args.reset
    run_id = args.run_id or f"{RUN_ID_PREFIX}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    source = getattr(args, 'source', 'district')

    # 支持多周期：--periods "2026年01月,2026年02月,..." (逗号分隔)
    periods_attr = getattr(args, 'periods', '') or ''
    if periods_attr:
        periods = [p.strip() for p in periods_attr.split(',') if p.strip()]
    else:
        single = getattr(args, 'period', '') or '2026年01月'
        periods = [single]

    # 索引初始化（一次性）
    _ensure_index(ES_INDEX, {
        "mappings": {
            "properties": {
                "breed":       {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
                "spec":        {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
                "unit":        {"type": "keyword"},
                "price":       {"type": "float"},
                "tax_price":   {"type": "float"},
                "is_tax":      {"type": "keyword"},
                "period":      {"type": "keyword"},
                "period_start":{"type": "date", "format": "yyyy-MM-dd"},
                "period_end":  {"type": "date", "format": "yyyy-MM-dd"},
                "period_days": {"type": "integer"},
                "province":    {"type": "keyword"},
                "city":        {"type": "keyword"},
                "county":      {"type": "keyword"},
                "area_code":   {"type": "keyword"},
                "category":    {"type": "keyword"},
                "source":      {"type": "keyword"},
                "update_date": {"type": "date", "format": "yyyy-MM-dd"},
                "create_time": {"type": "date", "format": "yyyy-MM-dd HH:mm:ss||yyyy-MM-dd||strict_date_optional_time"}
            }
        }
    })
    # v0.6 (2026-07-02) ：委托到 gov_price_etl.indexer.ensure_progress_index。
    _ensure_progress_index(ES_HOST, PROGRESS_INDEX)

    # 遍历每个 period
    for pi, target_period in enumerate(periods):
        month_num = re.search(r'(\d{1,2})月', target_period)
        if not month_num:
            print(f"[!] 无法从 '{target_period}' 提取月份，跳过")
            continue
        mn = month_num.group(1).zfill(2)

        # 第一个 period 才 reset，后续 period 同 run_id 续跑(ods 用 _id 幂等)
        is_first_period = (pi == 0)
        period_reset = reset and is_first_period

        print(f"\n{'#'*50}")
        print(f"# 周期 {target_period} ({pi+1}/{len(periods)})")
        print(f"{'#'*50}")

        # 单一 source 模式（CLI backward compat）
        if source != "all":
            _run_sync_source(source, tab_id, target_period, run_id, period_reset, mn)
            continue

        # 全量模式：依次跑 district / mortar / citywide
        # 同周期内多个 source 用 done_X 隔离进度,但都传到同一个 run_id
        for src in ["district", "mortar", "citywide"]:
            print(f"\n{'='*50}")
            print(f"[*] {target_period} - 开始同步: {src} ({SOURCE_CONFIG[src]['label']})")
            print(f"{'='*50}")
            # reset=True 时只对首个 source 生效(reset 会清掉本地进度文件)
            src_reset = period_reset if src == "district" else False
            _run_sync_source(src, tab_id, target_period, run_id, reset=src_reset, mn=mn)
            # 后续 source/period 续跑同一个 run_id
            period_reset = False


def _run_sync_source(source, tab_id, target_period, run_id, reset, mn):
    """针对单个 source 执行同步"""
    cfg = SOURCE_CONFIG.get(source, {})
    div_id = cfg.get("div_id", "")
    all_counties = _get_counties(source)
    item_label = cfg.get("item_label", "")

    prog = _load_progress()
    if reset:
        _reset_progress()
        prog = {"done": [], "run_id": run_id}
        print(f"[i] 已重置进度 ({source})")

    # load progress keyed by (source, period) — 跨月份隔离
    done_key = f"done_{source}_{target_period}"
    done_counties = prog.get(done_key, [])
    remaining = [c for c in all_counties if c not in done_counties]

    print(f"[*] source: {source}, 共 {len(all_counties)} 个区县，已完成 {len(done_counties)} 个，剩余 {len(remaining)} 个")
    print(f"[*] 目标周期: {target_period}")

    token = _load_gateway_token()
    if not token:
        print("[!] 未找到 Gateway token")
        return

    if not _focus_tab(tab_id):
        print(f"[!] 聚焦标签页失败")
        return

    print("[*] 点击'材料信息价'标签页...")
    if not _click_material_price_tab():
        print("[!] 点击材料信息价标签页失败")
        return
    time.sleep(2)

    print(f"[*] 点击子tab: {source} ({div_id})...")
    if not _click_source_tab(source):
        print(f"[!] 点击子tab失败: {source}")
        return
    time.sleep(2)

    print(f"[*] 选中月份: {mn}...")
    if not _select_month(mn, source):
        print(f"[!] 月份选择失败: {mn}")
        return
    time.sleep(1)

    interrupted = False
    def _sig_handler(s, f):
        nonlocal interrupted
        interrupted = True
    signal.signal(signal.SIGINT, _sig_handler)

    start_time = time.time()
    total_docs = 0

    # citywide 用分类 tab 迭代；其他用区县迭代
    if source == "citywide":
        categories = cfg.get("categories", [])
        remaining_cat = [c for c in categories if c not in done_counties]
        iter_items = list(enumerate(remaining_cat, len(done_counties) + 1))
        county_for_write = "主城区"
    else:
        iter_items = list(enumerate(remaining, len(done_counties) + 1))
        county_for_write = None  # 会从循环里取

    for i, item in iter_items:
        if interrupted:
            print("\n[!] 中断，保存进度...")
            prog[done_key] = done_counties
            _save_progress_all(prog, run_id)
            break

        if source == "citywide":
            county = county_for_write
            category = item
            label = category
        else:
            county = item
            category = ""
            label = county

        t0 = time.time()
        print(f"[{i}/{len(all_counties)}] >>> {label} [{source}]")

        try:
            if source == "citywide":
                # 点击分类 tab，等 AJAX
                ok = _click_category(category, div_id)
                if not ok:
                    print(f"  [!] 点击分类失败: {category}")
                    cmd_progress(run_id, label, target_period, 1, 1, 0, "error", "click failed", 0, source)
                    done_counties.append(category)
                    prog[done_key] = done_counties
                    _save_progress_all(prog, run_id)
                    continue
                time.sleep(random.randint(3, 5))
            else:
                ok = _click_county(county, source)
                if not ok:
                    print(f"  [!] 点击区县失败")
                    cmd_progress(run_id, county, target_period, 1, 1, 0, "error", "click failed", 0, source)
                    done_counties.append(county)
                    prog[done_key] = done_counties
                    _save_progress_all(prog, run_id)
                    continue
                time.sleep(random.randint(3, 5))

            # 等 AJAX 响应
            for _ in range(15):
                data = _extract_page(source)
                rows = data.get("rows", [])
                if rows:
                    break
                time.sleep(1)

            all_rows = []
            page = 1
            while page <= 50:
                data = _extract_page(source)
                rows = data.get("rows", [])
                total_pages = data.get("totalPages", 1)
                has_next = data.get("hasNext", False)
                all_rows.extend(rows)
                print(f"  page {page}/{total_pages}: +{len(rows)} rows")

                if page >= total_pages or not has_next:
                    break

                if not _click_next(source):
                    break
                # 等 AJAX 完成：页码变成 next_page 才继续
                next_page = page + 1
                for _ in range(12):
                    time.sleep(1)
                    data2 = _extract_page(source)
                    if data2.get('currentPage') == next_page:
                        break
                page = next_page

            n = cmd_write(run_id, county, target_period, json.dumps({"rows": all_rows}), source=source, category=category)
            duration = time.time() - t0
            status = "completed" if n > 0 else "error"
            cmd_progress(run_id, label, target_period, 1, 1, n, status, "", duration, source)
            total_docs += n
            done_counties.append(label)
            prog[done_key] = done_counties
            _save_progress_all(prog, run_id)

            icon = "✓" if status == "completed" else "✗"
            print(f"  [{icon}] {label}: 写入 {n} 条, {duration:.1f}s")

        except Exception as e:
            duration = time.time() - t0
            print(f"  [✗] {label}: {e}")
            cmd_progress(run_id, label, target_period, 1, 1, 0, "error", str(e), duration, source)
            done_counties.append(label)
            prog[done_key] = done_counties
            _save_progress_all(prog, run_id)

    duration_total = time.time() - start_time
    print(f"\n[DONE:{source}] {len(done_counties)}/{len(all_counties)} counties, {total_docs} docs, {duration_total:.1f}s")


def _save_progress_all(prog, run_id):
    """保存进度（支持多 source）"""
    prog["run_id"] = run_id
    prog["saved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(prog, f, ensure_ascii=False, indent=2)


def cmd_progress(run_id, county, period, page, total_pages, docs_written, status, error_msg, duration, source="district"):
    label_map = {"district": "区县材料", "mortar": "预拌砂浆", "citywide": "重庆材料信息价"}
    area_label = f"{label_map.get(source, source)}-{county}"
    # 计算 percent：完成或错误状态为 100，否则按页数比例
    if status in ("completed", "error"):
        percent = 100.0
    elif total_pages and total_pages > 0:
        percent = round(page / total_pages * 100, 1)
    else:
        percent = 0.0
    body = {
        "run_id": run_id, "area": area_label, "period": period,
        "current_page": page, "total_pages": total_pages,
        "docs_written": docs_written, "status": status,
        "duration_sec": duration, "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "error": error_msg or "",
        "source": source, "percent": percent,
    }
    # 固定 _id:同 (run_id, source, county, period) 复用,跨月份隔离
    _id = f"{run_id}__{source}__{county}__{period}"
    try:
        r = requests.put(f"{ES_HOST}/{PROGRESS_INDEX}/_doc/{_id}", json=body, timeout=15, verify=False)
        return r.status_code in (200, 201)
    except Exception:
        return False


def cmd_write(run_id, county, period, result_json, source="district", category=""):
    """将抓取的 rows 解析并写入 ES"""
    try:
        result = json.loads(result_json)
        rows = result.get("rows", [])
    except Exception:
        rows = []

    if not rows:
        return 0

    period_date = f"{period.replace('年', '-').replace('月', '-01')}"
    if len(period_date) > 10:
        period_date = period_date[:10]

    # 兼容缺少年份的 period（如 '01月'），默认 2026
    if len(period_date) < 10:
        period_date = f"2026-{period_date[5:]}"  # 兜底

    # 推导 period_end（当月最后一天）+ period_days
    import calendar
    try:
        year, month, _ = period_date.split("-")
        y, m = int(year), int(month)
        last_day = calendar.monthrange(y, m)[1]
    except Exception:
        last_day = 28
    period_end_date = f"{period_date[:8]}{last_day:02d}"

    col_map = _columns_for(category)
    is_landscape = category == "园林绿化工程材料"

    docs = []
    # 4 道保护 (v4.1 2026-07-02) ：如果 6 月份原站表格结构变了，sync 不会默默漏抓
    counters = {
        "col_count_short": 0,        # 保护1：列数不够（特别是园林景观原站表头变化）
        "col_count_short_samples": [],  # 样本
        "price_parse_fail": 0,       # 保护2：价格列有值但 price_min=0（区间解析失败）
        "price_parse_fail_samples": [],
    }

    for row in rows:
        if len(row) < 6:
            continue

        # ── 保护 1：列数自检 ─────────────────────
        # 园林景观原站表格是 11 列（[序号,科属,品名,高度,干径,冠径,分枝高,单位,含税价,不含税价,备注]）。
        # 如果以后原站列数变化（比如加 1 列变成 12 列），这里会拦截，不会默默接受错位数据。
        if is_landscape and len(row) < 11:
            counters["col_count_short"] += 1
            if len(counters["col_count_short_samples"]) < 3:
                counters["col_count_short_samples"].append({
                    "row_len": len(row),
                    "row_head": row[:6],
                })
            continue  # 跳过这行，不入 ES

        # ── 按列映射取字段 ─────────────────────────
        def _cell(idx):
            return row[idx].strip() if idx < len(row) and row[idx] else ""

        breed = _cell(col_map.get("breed", 1))
        if not breed or breed == "材料名称":
            continue

        # spec：园林景观走合成，其他取 row[2]
        if is_landscape:
            spec = _build_spec_for_landscape(row, col_map)
        else:
            spec = _cell(col_map.get("spec", 2))
        unit = _cell(col_map.get("unit", 3))

        # 园林景观的价格列：row[8]=含税 row[9]=不含税
        # 建安类价格列：row[4]=含税 row[5]=不含税（与重庆 SKILL 一致）
        # 统一从 col_map 读索引
        tax_str = _cell(col_map.get("tax_price", 4))
        price_str = _cell(col_map.get("price", 5))

        # ── 价格解析（走区间解析） ─────────────────
        price_mid, price_min, price_max, is_range, price_range_str, notes = _parse_interval_price(
            price_str if price_str else tax_str
        )
        tax_mid, tax_min, tax_max, _, tax_range_str, _ = _parse_interval_price(
            tax_str if tax_str else price_str
        )

        # ── 保护 2：价格解析失败告警 ─────────────────
        # 园林景观源站价格列总是有值（"115-173" / "大于200" / "全冠"）。
        # 如果 price_str 有值（且不是 "0"）但 price_min=0，说明区间解析可能挂了。
        # 例：原站以后加了新格式 "200元/株" / "0.2万/棵" / "面议" 之类。
        # 合法 special value（"全冠" / "全干"）走 notes 路径，不告警。
        _KNOWN_SPECIAL = {"全冠", "全干"}
        if is_landscape and price_str and price_str != "0" and price_min == 0 and price_str not in _KNOWN_SPECIAL:
            counters["price_parse_fail"] += 1
            if len(counters["price_parse_fail_samples"]) < 3:
                counters["price_parse_fail_samples"].append({
                    "breed": breed,
                    "spec": spec,
                    "raw_price": price_str,
                })
            # 不 continue ——后续 _is_price_valid 会过滤 price_min=0 不入 DWS。
            # 告警仅打印，不阻断写入（能让我们看到原站源数据）。

        # ── is_tax 推断 ────────────────────────────
        if price_str and not tax_str:
            is_tax_val = "0"   # 只有不含税
        elif tax_str and not price_str:
            is_tax_val = "1"   # 只有含税（园林景观的常态）
        else:
            is_tax_val = "1"

        # ── 构造 doc ────────────────────────────────
        doc = {
            "breed": breed,
            "spec": spec,
            "unit": unit,
            "price": price_mid,
            "tax_price": tax_mid,
            "price_min": price_min,
            "price_max": price_max,
            "price_range": price_range_str,
            "is_range": is_range,
            "is_tax": is_tax_val,
            "period": period_date,
            "period_start": period_date,
            "period_end": period_end_date,
            "period_days": last_day,
            "province": "重庆",
            "city": "重庆",
            "county": county,
            "area_code": "500000",
            "category": category,
            "update_date": period_date,
            "source": source,
            "run_id": run_id,
            "create_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        if notes:
            doc["range_notes"] = notes

        # 园林景观的额外维度：科属（category_l1）+ 4 个维度进 range_notes 后缀
        if is_landscape:
            ql = _cell(col_map.get("category_l1", 1))
            if ql:
                doc["spec_notes"] = ql   # 科属（乔木/花灌木/棕榈植物类）

        docs.append(doc)

    # ── 保护 1/2 告警 summary ─────────────────
    if counters["col_count_short"] > 0:
        print(f"  [WARN\u26a0\ufe0f \u4fdd\u62a41] \u56ed\u6797\u666f\u89c2\u5217\u6570\u4e0d\u8db3 11 \u5217\uff1a{counters['col_count_short']} \u884c\u88ab\u8df3\u8fc7")
        for s in counters["col_count_short_samples"]:
            print(f"    \u793a\u4f8b row_len={s['row_len']}, head={s['row_head']}")
    if counters["price_parse_fail"] > 0:
        print(f"  [WARN\u26a0\ufe0f \u4fdd\u62a42] \u4ef7\u683c\u89e3\u6790\u5931\u8d25\uff08\u6709\u539f\u6587\u4f46 price_min=0\uff09\uff1a{counters['price_parse_fail']} \u6761")
        for s in counters["price_parse_fail_samples"]:
            print(f"    \u793a\u4f8b breed={s['breed']!r} spec={s['spec']!r} raw_price={s['raw_price']!r}")

    if not docs:
        return 0

    actions = ""
    for d in docs:
        actions += json.dumps({"index": {}}, ensure_ascii=False) + "\n"
        actions += json.dumps(d, ensure_ascii=False) + "\n"

    try:
        r = requests.post(f"{ES_HOST}/{ES_INDEX}/_bulk", data=actions.encode("utf-8"),
                         headers={"Content-Type": "application/x-ndjson"}, timeout=30)
        resp = r.json()
        return sum(1 for item in resp.get("items", []) if item.get("index", {}).get("status") in (200, 201))
    except Exception:
        return 0


def _safe_float(s):
    try:
        return float(s)
    except Exception:
        return 0.0


# _parse_interval_price 已迁到 gov_price_etl.parse_price.parse_interval_price
# (顶部 import 时取别名 _parse_interval_price，调用点保持不变)。
# 2026-07-02 删除本地实现，单一权威避免双份维护。新加 corner case 请改
# gov_price_etl/parse_price.py，所有城市（chongqing/jiangxi/sichuan...）同步受益。


# ── 列映射：按 category 选列 ─────────────────────────────
COLUMN_MAPS = {
    # 默认：建安工程 / 绿色节能 / 装配式 / 轨道（7 列）
    # [序号, 材料名称, 规格型号, 单位, 含税价, 不含税价, 备注]
    "default": {
        "breed": 1, "spec": 2, "unit": 3,
        "tax_price": 4, "price": 5, "remark": 6,
    },
    # 园林景观（11 列）
    # [序号, 科属, 品名, 高度, 干径, 冠径, 分枝高, 单位, 含税价, 不含税价, 备注]
    "园林绿化工程材料": {
        "category_l1": 1,        # 科属（乔木/花灌木 等）
        "breed": 2,              # 品名（小叶榕）
        "_spec_components": [3, 4, 5, 6],  # 高度/干径/冠径/分枝高 合成 spec
        "_height": 3,
        "_trunk_diameter": 4,
        "_crown_diameter": 5,
        "_branch_height": 6,
        "unit": 7,
        "tax_price": 8, "price": 9,
        "remark": 10,
    },
}


def _build_spec_for_landscape(row, m):
    """园林景观类的 spec 合成：'干径Φ7-9cm 冠径>200cm 分枝高200-220cm'

    _safe_float_interval 对 raw 字符串保留好，spec 用 raw 拼。
    """
    parts = []
    labels = [
        (m['_height'],         '高'),
        (m['_trunk_diameter'], '干径'),
        (m['_crown_diameter'], '冠径'),
        (m['_branch_height'],  '分枝高'),
    ]
    for idx, label in labels:
        val = row[idx] if idx < len(row) else ''
        if val and val.strip():
            parts.append(f"{label}{val.strip()}")
    return ' '.join(parts)


def _columns_for(category):
    """按 category 返回列映射，未识别走 default。"""
    return COLUMN_MAPS.get(category, COLUMN_MAPS['default'])


def cmd_init():
    pass  # index created on-demand


# ─── CLI 入口 ────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: write_es.py <init|write|progress|summary|sync> ...")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "init":
        cmd_init()

    elif cmd == "write":
        run_id = sys.argv[2]
        county = sys.argv[3]
        period = sys.argv[4]
        result_json = sys.argv[5]
        cmd_write(run_id, county, period, result_json)

    elif cmd == "progress":
        run_id = sys.argv[2]
        county = sys.argv[3]
        period = sys.argv[4]
        current_page = int(sys.argv[5])
        total_pages = int(sys.argv[6])
        docs_written = int(sys.argv[7])
        status = sys.argv[8]
        error = sys.argv[9] if len(sys.argv) > 9 else ""
        duration = float(sys.argv[10]) if len(sys.argv) > 10 else 0
        cmd_progress(run_id, county, period, current_page, total_pages, docs_written, status, error, duration)

    elif cmd == "summary":
        run_id = sys.argv[2]
        total_counties = int(sys.argv[3])
        completed = int(sys.argv[4])
        total_docs = int(sys.argv[5])
        duration_sec = float(sys.argv[6])
        period = sys.argv[7] if len(sys.argv) > 7 else "2026年01月"
        cmd_summary(run_id, period, total_counties, completed, total_docs, duration_sec)

    elif cmd == "sync":
        parser = argparse.ArgumentParser(description="重庆工程造价材料信息同步")
        parser.add_argument("--reset", action="store_true", help="重置进度，重新开始")
        parser.add_argument("--period", default="2026年01月", help="目标周期（兼容旧参数，等价 --periods 单值）")
        parser.add_argument("--periods", default="", help="多周期，逗号分隔，如 '2026年01月,2026年02月'")
        parser.add_argument("--tab-id", default="", help="浏览器 tab targetId")
        parser.add_argument("--run-id", default="", help="指定 run_id")
        parser.add_argument("--source", default="district",
                            help="数据来源: district / mortar / citywide / all")
        args = parser.parse_args(sys.argv[2:])
        cmd_sync(args)

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
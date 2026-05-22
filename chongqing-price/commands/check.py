#!/usr/bin/env python3
"""重庆工程造价材料信息 - 增量检测与触发同步

检测逻辑：
1. 用 browser 提取当前页面显示的周期下拉框，找到最新周期
2. 对比 config 中 last_period：不同 → 有新周期，触发全量同步
3. 对比 ES 中最新已完成周期：比 config 更新 → 网站已有新数据，触发增量
4. 当前周期未完成 → 触发断点续传

前置条件：browser 已打开目标页面并聚焦在正确 tab
"""
import sys, os, json, time, subprocess, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
warnings.filterwarnings('ignore')
import requests
import yaml

ES_HOST = "http://localhost:59200"

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.yml")

def _es_config():
    with open(CONFIG_PATH, encoding='utf-8') as f:
        return yaml.safe_load(f) or {}

_es_cfg = _es_config()

ALL_COUNTIES = [
    "主城区", "万州区", "涪陵区", "黔江区", "长寿区", "江津区", "合川区",
    "永川区", "南川区", "梁平区", "城口县", "丰都县", "垫江县", "忠县",
    "开州区", "云阳县", "奉节县", "巫山县", "巫溪县", "石柱县", "秀山县",
    "酉阳县", "大足区", "綦江区", "万盛经开区", "双桥经开区", "铜梁区",
    "璧山区", "彭水县1", "彭水县2", "彭水县3", "荣昌区1", "荣昌区2",
    "潼南区", "武隆区",
]


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
    s = s.replace('\\"', '"')
    return s


def _check_browser_tab(tab_label="重庆市建设工程造价信息网") -> str | None:
    """检查 browser tab 是否存在，返回 tab_id 或 None"""
    out, _ = _run_cli(["browser", "tabs"])
    for line in out.splitlines():
        if tab_label in line:
            # 从 "tab: t1" 或 "[t1]" 提取 tab id
            m = re.search(r'\[?t(\d+)\]?', line)
            if m:
                return f"t{m.group(1)}"
    return None


def _focus_tab(tab_id: str) -> bool:
    out, _ = _run_cli(["browser", "focus", tab_id])
    return "focused" in out.lower() or "ok" in out.lower()


def get_current_period_from_page() -> str | None:
    """从页面提取当前选中的周期名称（从周期下拉框）"""
    js = '''(function(){
var selects = document.querySelectorAll("select");
for(var i=0;i<selects.length;i++){
  var opts = selects[i].options;
  for(var j=0;j<opts.length;j++){
    if(opts[j].selected && opts[j].value){
      return opts[j].text.trim();
    }
  }
  if(selects[i].value){
    return selects[i].selectedOptions[0].text.trim();
  }
}
return null;
})()'''
    try:
        result = _eval_js(js)
        if result and result != "null":
            return result.strip()
    except Exception:
        pass
    return None


def get_all_period_options() -> list[str]:
    """提取页面所有周期选项（从下拉框）"""
    js = '''(function(){
var selects = document.querySelectorAll("select");
var periods = [];
for(var i=0;i<selects.length;i++){
  var opts = selects[i].options;
  for(var j=0;j<opts.length;j++){
    if(opts[j].value && opts[j].value.trim()){
      periods.push(opts[j].text.trim());
    }
  }
}
return JSON.stringify(periods);
})()'''
    try:
        raw = _eval_js(js)
        if raw and raw != "null":
            periods = json.loads(raw)
            return periods
    except Exception:
        pass
    return []


def get_es_last_completed_period() -> str | None:
    """从 ES 查最新已完成周期的 period 字段"""
    try:
        r = requests.get(
            f"{ES_HOST}/{PROGRESS_INDEX}/_search?size=200&sort=last_updated:desc",
            timeout=15, verify=False
        )
        if r.status_code != 200:
            return None
        hits = r.json().get("hits", {}).get("hits", [])
        periods = set()
        for h in hits:
            src = h.get("_source", {})
            if src.get("status") == "completed" and src.get("period"):
                periods.add(src["period"])
        if periods:
            # 取最新的 period（格式如 2026-01-01）
            sorted_periods = sorted(periods)
            return sorted_periods[-1]
    except Exception:
        pass
    return None


def get_es_completed_county_count(period: str) -> int:
    """统计 ES 中某周期已完成区县数量"""
    try:
        body = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"status": "completed"}},
                        {"term": {"period": period}},
                    ]
                }
            }
        }
        r = requests.post(
            f"{ES_HOST}/{PROGRESS_INDEX}/_count",
            json=body, timeout=15, verify=False
        )
        if r.status_code == 200:
            return r.json().get("count", 0)
    except Exception:
        pass
    return 0


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def save_config(cfg: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)


def trigger_sync(period: str, tab_id: str, reset: bool = False):
    """触发后台同步"""
    log_file = f"/tmp/chongqing-incremental-sync-{int(time.time())}.log"
    cmd = ["python3", "commands/sync.py"]
    if reset:
        cmd.append("--reset")
    cmd.extend(["--period", period, "--tab-id", tab_id])
    ret = subprocess.Popen(
        cmd,
        cwd=SCRIPT_DIR,
        env={**os.environ},
        stdout=open(log_file, "w"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return ret.pid, log_file


def main():
    print("[i] 重庆增量检测开始...")

    # 1. 检查 browser tab
    tab_id = _check_browser_tab()
    if not tab_id:
        print("[!] browser 未打开或目标 tab 不存在，请先运行：")
        print("    openclaw browser open 'http://www.cqsgczjxx.org/Pages/CQZJW/priceInformation.aspx'")
        print("[!] 跳过本次检测")
        return

    print(f"[*] 找到 browser tab: {tab_id}")

    # 2. 聚焦 tab
    if not _focus_tab(tab_id):
        print("[!] 聚焦 browser tab 失败")
        return
    time.sleep(1)

    # 3. 提取 config 中的 last_period
    cfg = load_config()
    last_period_cfg = cfg.get("sync", {}).get("last_period", "") or ""
    print(f"[*] config last_period: {last_period_cfg or '(空)'}")

    # 4. 点击「材料信息价」标签页（只关注该分类的数据）
    print("[*] 点击'材料信息价'标签页...")
    js_click_tab = '''(function(){
var navs = document.querySelectorAll(".priceNav");
for(var i=0;i<navs.length;i++){
  if(navs[i].innerText.trim()==="材料信息价"){navs[i].click();return"OK";}
}
return"NOT_FOUND";
})()'''
    click_out, _ = _run_cli(["browser", "evaluate", "--fn", js_click_tab])
    if "OK" not in click_out:
        print("[!] 未找到'材料信息价'标签页，跳过")
        return
    print("[*] 已点击'材料信息价'")
    time.sleep(2)


    # 5. 从 browser 提取页面当前周期和所有周期选项
    current_period = get_current_period_from_page()
    all_periods = get_all_period_options()

    if not current_period:
        print("[!] 无法从页面提取当前周期，可能页面未加载完成")
        print("[!] 跳过本次检测")
        return

    print(f"[*] 页面当前周期: {current_period}")
    if all_periods:
        latest_site_period = all_periods[0]  # 下拉框第一个通常是最新
        print(f"[*] 网站最新周期: {latest_site_period}")
        print(f"[*] 全部周期选项: {', '.join(all_periods[:5])}{'...' if len(all_periods) > 5 else ''}")
    else:
        latest_site_period = current_period
        print(f"[*] 无法获取周期下拉列表，使用当前周期: {current_period}")

    # 5. 判断：config.last_period vs 页面当前周期
    needs_full_sync = False
    target_period = current_period

    if last_period_cfg and current_period != last_period_cfg:
        # config 有记录但与页面当前周期不同 → 有新周期
        print(f"\n[✓] 发现新周期: {current_period} (旧: {last_period_cfg})")
        needs_full_sync = True
        target_period = current_period
    elif not last_period_cfg:
        # 从未同步过
        print(f"\n[✓] 首次同步，周期: {current_period}")
        needs_full_sync = True
    else:
        # config 与当前周期一致，检查 ES 中最新已完成周期
        es_last = get_es_last_completed_period()
        print(f"[*] ES 最新已完成周期: {es_last or '(无)'}")

        if es_last and es_last > last_period_cfg:
            print(f"\n[✓] ES 已有新数据: {es_last} > config.last_period ({last_period_cfg})")
            needs_full_sync = True
            target_period = es_last
        else:
            # 检查当前周期是否完成
            completed = get_es_completed_county_count(last_period_cfg)
            total = len(ALL_COUNTIES)
            if completed < total:
                print(f"\n[✓] 当前周期 {last_period_cfg} 未完成: {completed}/{total} 区县")
                needs_full_sync = True
                target_period = last_period_cfg
            else:
                print(f"\n[—] 无新增数据，当前周期 {last_period_cfg} 已全部完成 ({completed}/{total} 区县)")
                return

    # 6. 更新 config.last_period
    if needs_full_sync and target_period != last_period_cfg:
        cfg.setdefault("sync", {})["last_period"] = target_period
        save_config(cfg)
        print(f"[*] config.last_period 已更新为: {target_period}")

    # 7. 触发同步
    print(f"\n[→] 触发同步: 周期={target_period}, tab={tab_id}（后台运行）...")
    pid, log_file = trigger_sync(target_period, tab_id, reset=(not last_period_cfg))
    print(f"[→] 同步已在后台启动 (PID {pid})")
    print(f"[→] 日志: {log_file}")
    print("[✓] check.py 完成，sync.py 继续在后台运行")


if __name__ == "__main__":
    main()

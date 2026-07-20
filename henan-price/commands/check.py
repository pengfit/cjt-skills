import os
STATUS_DIR = os.environ.get("GOV_CHECK_STATUS_DIR", "/tmp/gov-check-status")
SUMMARY_DIR = os.environ.get("GOV_PRICE_SUMMARY_DIR", "/tmp/gov-price-summary")

"""河南 - 增量检测：对比 ES 最新 update_date vs 源站最新发布日期"""
def _resolve_etl_root():
    """解析 gov-price-etl 项目根路径。

    优先级：
      1) 环境变量 GOV_PRICE_ETL_ROOT（部署/调试可显式覆盖）
      2) 自动反推：从本文件路径向上找 'gov-price-etl' 同级目录，
         不依赖硬编码的 workspace 名 / 目录深度。
      3) 兜底扫描：~/.openclaw/workspace/*/skills/gov-price-etl,
         不预设 workspace 名。
      4) 仍找不到：抛错提示用户设环境变量。绝不默默返回错误路径。
    """
    import os
    from pathlib import Path
    env = os.environ.get("GOV_PRICE_ETL_ROOT")
    if env and os.path.isdir(env):
        return env
    p = Path(__file__).resolve().parent
    for _ in range(6):
        candidate = p / "gov-price-etl"
        if candidate.is_dir():
            return str(candidate)
        p = p.parent
    workspace_root = Path.home() / ".openclaw" / "workspace"
    if workspace_root.is_dir():
        for ws in workspace_root.iterdir():
            candidate = ws / "skills" / "gov-price-etl"
            if candidate.is_dir():
                return str(candidate)
    raise FileNotFoundError(
        "找不到 gov-price-etl 项目根。"
        "请设置环境变量 GOV_PRICE_ETL_ROOT 指向项目根，"
        "或确认 ETL 已部署在 <workspace>/skills/gov-price-etl。"
    )


import sys, os, re
from urllib.parse import urljoin
from bs4 import BeautifulSoup

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from utils import load_config, get_es_client, fetch_html


def main():
    cfg = load_config()
    es = get_es_client(cfg['es']['host'])
    site = cfg['site']
    base = site['base_url']
    headers = {'User-Agent': site['user_agent']}
    ods_index = cfg['es']['ods_index']

    # 1. 获取 ES 最新 update_date
    es_latest = ''
    try:
        r = es.search(index=ods_index, size=1, sort=[{'update_date': 'desc'}],
                       _source=['update_date'])
        hits = r['hits']['hits']
        if hits:
            es_latest = hits[0]['_source'].get('update_date', '') or ''
    except Exception as e:
        print(f'[河南] ES 查询失败: {e}')

    # 2. 获取源站最新发布日期（只看第1页最新一条）
    site_latest = ''
    site_title = ''
    try:
        list_url = f'{base}/jcxx/004001/1.html'
        html = fetch_html(list_url, headers=headers)
        soup = BeautifulSoup(html, 'html.parser')
        first_li = soup.select_one('li.ewb-right-item')
        if first_li:
            date_el = first_li.select_one('span.ewb-right-date')
            if date_el:
                site_latest = date_el.get_text(strip=True)
            a = first_li.select_one('a[title]')
            if a:
                site_title = a.get('title', '')
    except Exception as e:
        print(f'[河南] 源站查询失败: {e}')

    print(f'[河南] 源站最新: {site_title} ({site_latest})')
    print(f'[河南] ES 最新:   {es_latest or "无"}')

    if es_latest and site_latest:
        if site_latest > str(es_latest)[:10]:
            print(f'[河南] 🔔 有更新！{site_title}')
        else:
            print(f'[河南] ✅ 无新数据')
    elif site_latest:
        print(f'[河南] 🔔 源站有数据，ES 无记录，需首次同步')
    else:
        print(f'[河南] ⚠️ 无法获取源站数据')


# === dashboard status 同步（v0.8.1, 2026-07-03）===
# 捕获 main() 的 stdout，按末行 [城市] 状态写到 STATUS_DIR/<key>.json
# 供 dashboard /sync 顶部 chip 复用。已存在则覆盖。
if __name__ == '__main__':
    import sys as _sys, io as _io
    _buf = _io.StringIO()
    _old_stdout = _sys.stdout
    _sys.stdout = _buf
    try:
        main()
    finally:
        _sys.stdout = _old_stdout
    _output = _buf.getvalue()
    print(_output, end='')  # 完整回放到屏幕（保留原行为）

    # 写 check_status json
    try:
        _etl_root = _resolve_etl_root()
        if _etl_root not in _sys.path:
            _sys.path.insert(0, _etl_root)
        from gov_price_etl.check_status import write_status_from_check_output
        write_status_from_check_output('henan', '河南', _output)
    except Exception as _e:
        print(f'⚠️ check_status 失败: {_e}', file=_sys.stderr)

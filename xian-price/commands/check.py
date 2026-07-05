"""西安 - 增量检测: 对比 ES 各 county 最新 month vs 源站各 county 最新 period

修复记录(v0.2): 
- 原版用 ES `update_date`(数据抓取入库时间)和 HTML 页脚日期对比, 错位严重
  例如 sync 抓完一批后 update_date 是抓取当天(如 2026-06-22), 但源站数据月还是 2026-02
- 原版 `periods[-1]` 取源站 list_periods 最后一个, 但源站 API 返回倒序(最新在前), 
  所以 [-1] 实际是最旧的
- 修正: 按 `month` 字段(YYYY-MM)聚合对比 `period` 字段, 每个 county 独立判断
"""
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


import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))
CONFIG_PATH = SCRIPT_DIR / 'config.yml'

from commands.utils import SiteSession, COUNTY_CODES, load_config, list_all_years
from elasticsearch import Elasticsearch


def get_es_max_month(es: Elasticsearch, index: str) -> dict:
    """从 ES 拉每个 county 最新 month(YYYY-MM).

    Returns:
        {county: 'YYYY-MM', ...}
    """
    out = {}
    try:
        r = es.search(
            index=index,
            size=0,
            aggs={
                "by_county": {
                    "terms": {"field": "county", "size": 50},
                    "aggs": {
                        "by_month": {
                            "terms": {"field": "month", "size": 5, "order": {"_key": "desc"}}
                        }
                    }
                }
            }
        )
        for c in r.get('aggregations', {}).get('by_county', {}).get('buckets', []):
            months = c.get('by_month', {}).get('buckets', [])
            if months:
                out[c['key']] = months[0]['key']
    except Exception as e:
        print(f'[西安] ES 查询失败: {e}')
    return out


def get_site_max_period(sess: SiteSession) -> dict:
    """从源站拉每个 county 最新 period(YYYY-MM).

    Returns:
        {county: 'YYYY-MM', ...}
    """
    out = {}
    for county in COUNTY_CODES:
        ys = list_all_years(county, sess)
        if not ys:
            continue
        max_year = max(ys)
        periods = sess.list_periods(county, max_year)
        if not periods:
            continue
        # list_periods 源站 API 返回顺序是**倒序**(最新在前)
        # 但稳妥起见按 period 字段降序取 max
        valid = [p for p in periods if p.get('period', '')]
        if not valid:
            continue
        latest = max(valid, key=lambda p: p['period'])
        out[county] = latest['period']
    return out


def main():
    cfg = load_config(CONFIG_PATH)
    es = Elasticsearch(cfg['es']['host'])
    ods_index = cfg['es']['index']
    sess = SiteSession()

    # 1. ES 各 county 最新 month
    es_months = get_es_max_month(es, ods_index)

    # 2. 源站各 county 最新 period
    site_periods = get_site_max_period(sess)

    # 3. 对比
    print(f'[西安] 源站 vs ES 月份对比: ')
    print(f'  {"county":8s} {"源站period":12s} {"ES month":12s} {"差":6s} 状态')
    any_behind = False
    any_extra = False
    for county in sorted(set(site_periods) | set(es_months)):
        sp = site_periods.get(county, '?')
        em = es_months.get(county, '?')
        if sp == '?':
            print(f'  {county:8s} {sp:12s} {em:12s}  -     源站无数据')
            continue
        if em == '?':
            print(f'  {county:8s} {sp:12s} {em:12s}  -     ES 无 month(未指定 --period 同步?)')
            any_behind = True
            continue
        if sp > em:
            diff = f'+{sp[5:]}-vs-{em[5:]}月'  # 缺几个月
            print(f'  {county:8s} {sp:12s} {em:12s}  -{sp[5:]}>{em[5:]}  🔔 ES 缺 {sp[5:]} 月')
            any_behind = True
        elif em > sp:
            print(f'  {county:8s} {sp:12s} {em:12s}  +{em[5:]}    ⚠️ ES 多于源站(异常)')
            any_extra = True
        else:
            print(f'  {county:8s} {sp:12s} {em:12s}  ok     ✅ 已同步')

    print()
    if any_behind:
        print(f'[西安] 🔔 有区县缺月, 建议跑: ')
        print(f'  ./run.sh sync --period <缺月> --counties <county>')
    elif any_extra:
        print(f'[西安] ⚠️ 有区县 ES 多于源站, 请人工核查')
    else:
        print(f'[西安] ✅ 全部区县已与源站对齐')


# === dashboard status 同步（v0.8.1, 2026-07-03）===
# 捕获 main() 的 stdout，按末行 [城市] 状态写到 /tmp/gov-check-status/<key>.json
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
        write_status_from_check_output('xian', '西安', _output)
    except Exception as _e:
        print(f'⚠️ check_status 失败: {_e}', file=_sys.stderr)

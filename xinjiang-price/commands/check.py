"""新疆 - 增量检测：对比 ES 最新 update_date vs 源站最新政策（按 area 汇总）"""
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
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import load_config, get_es_client
from fetch import fetch_all_policies, filter_target_year, release_date_iso


def main():
    cfg = load_config()
    es = get_es_client(cfg['es']['host'])
    ods_index = cfg['es']['ods_index']
    year = cfg['sync']['year']

    print(f'[xinjiang] 检测年份: {year}')
    print(f'[xinjiang] ES 索引: {ods_index}')
    print()

    has_updates = False
    for area in cfg['areas']:
        areaid = area['areaid']
        try:
            policies = fetch_all_policies(cfg, areaid)
            targets = filter_target_year(policies, year)
        except Exception as e:
            print(f'  [{areaid}] {area["name"]:8s} ✗ 抓取失败: {e}')
            continue

        # ES 该 area 已有记录数
        es_count = 0
        es_latest = ''
        try:
            r = es.search(
                index=ods_index,
                size=1,
                query={'term': {'_areaid': str(areaid)}},
                sort=[{'update_date': 'desc'}],
                _source=['update_date'],
            )
            hits = r['hits']['hits']
            if hits:
                es_latest = hits[0]['_source'].get('update_date', '') or ''
            cnt = es.count(index=ods_index, query={'term': {'_areaid': str(areaid)}})
            es_count = cnt['count']
        except Exception:
            pass

        # 源站最新
        site_latest = release_date_iso(targets[0]['ReleaseDate']) if targets else ''
        site_count = len(targets)

        status = '✅'
        if not targets:
            status = '⚠️ 无目标'
        elif es_count == 0:
            status = '🔔 待首次'
            has_updates = True
        elif site_latest and es_latest and site_latest > es_latest:
            status = '🔔 有更新'
            has_updates = True
        elif es_count < site_count * 50:  # 经验阈值：每个政策平均 50 行
            status = '🔔 可能缺'
            has_updates = True

        print(f'  [{areaid:2d}] {area["name"]:8s}  源站 {site_count:3d} 期  ES {es_count:5d} 条  '
              f'源最新 {site_latest or "-"}  ES最新 {es_latest or "-"}  {status}')

    print()
    if has_updates:
        print('[xinjiang] 有待同步数据，运行 sync.py')
    else:
        print('[xinjiang] ✅ 所有 area 都是最新')


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
        write_status_from_check_output('xinjiang', '新疆', _output)
    except Exception as _e:
        print(f'⚠️ check_status 失败: {_e}', file=_sys.stderr)

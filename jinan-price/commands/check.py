"""济南 - 增量检测：对比 ES 最新入库周期 vs 源站最新周期"""
def _resolve_etl_root():
    """解析 gov-price-etl 项目根路径。

    优先级：
      1) 环境变量 GOV_PRICE_ETL_ROOT（部署/调试可显式覆盖）
      2) 自动反推：从本文件路径向上找 'gov-price-etl' 同级目录，
         不依赖硬编码的 workspace 名 / 目录深度。
      3) 兜底 fallback（cjt 子目录布局），让上层 log warning，不抛异常。
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
    return str(Path.home() / ".openclaw" / "workspace" / "cjt" / "skills" / "gov-price-etl")


import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(SCRIPT_DIR, 'config.yml')

from commands.utils import JinAnSiteSession, load_config
from elasticsearch import Elasticsearch


def main():
    cfg = load_config(CONFIG_PATH)
    es = Elasticsearch(cfg['es']['host'])
    ods_index = cfg['es']['index']
    session = JinAnSiteSession()

    # 1. 获取 ES 最新 period
    es_latest_period = ''
    try:
        r = es.search(index=ods_index, size=1, sort=[{'update_date': 'desc'}],
                       _source=['update_date', 'period'])
        hits = r['hits']['hits']
        if hits:
            es_latest_period = hits[0]['_source'].get('period', '') or ''
    except Exception as e:
        print(f'[济南] ES 查询失败: {e}')

    # 2. 获取源站最新周期
    site_period = ''
    try:
        period_name, period_id = session.get_last_period()
        site_period = period_name
    except Exception as e:
        site_period = cfg.get('sync', {}).get('last_period', '')
        print(f'[济南] 源站查询异常，使用 config: {e}')

    print(f'[济南] 源站最新周期: {site_period}')
    print(f'[济南] ES 最新入库:   {es_latest_period or "无"}')

    if site_period and (not es_latest_period or site_period > es_latest_period):
        print(f'[济南] 🔔 有更新！源站 {site_period}')
    else:
        print(f'[济南] ✅ 无新数据')


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
        write_status_from_check_output('jinan', '济南', _output)
    except Exception as _e:
        print(f'⚠️ check_status 失败: {_e}', file=_sys.stderr)

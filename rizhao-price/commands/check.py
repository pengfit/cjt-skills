"""日照 - 增量检测：对比 ES 最新 update_date vs 源站最新周期"""
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


import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(SCRIPT_DIR, 'config.yml')

from commands.utils import load_config
from elasticsearch import Elasticsearch


def main():
    cfg = load_config(CONFIG_PATH)
    es = Elasticsearch(cfg['es']['host'])
    ods_index = cfg['es']['index']
    sync_cfg = cfg.get('sync', {})

    # 1. 获取 ES 最新入库日期 + period（v0.8.2, 2026-07-06）
    es_latest = ''
    es_latest_period = ''
    try:
        r = es.search(index=ods_index, size=1, sort=[{'update_date': 'desc'}],
                       _source=['update_date', 'period'])
        hits = r['hits']['hits']
        if hits:
            es_latest = hits[0]['_source'].get('update_date', '') or ''
            es_latest_period = hits[0]['_source'].get('period', '') or ''
    except Exception as e:
        print(f'[日照] ES 查询失败: {e}')

    # 2. 源站"上次同步周期"——从 config.yml 读取。
    #    注：日照源站是内网 OA 系统，需登录才能抓取，check 不远程去拉；
    #    config.last_period 需要道友在 sync 后手动维护（或 sync 脚本自动写）。
    last_period = sync_cfg.get('last_period', '')

    print(f'[日照] config 上次同步周期: {last_period}')
    print(f'[日照] ES 最新入库:         {es_latest or "无"}')
    print(f'[日照] ES 最新 period:      {es_latest_period or "无"}')

    # 3. 判定：优先看 ES period 跟 config 是否对齐
    if not es_latest_period:
        print(f'[日照] 🔔 ES 无数据，需首次同步')
    elif not last_period:
        print(f'[日照] ⚠️ config 缺 last_period，请 sync 后填上（ES 已有 {es_latest_period}）')
    elif es_latest_period >= last_period:
        print(f'[日照] ✅ 已对齐（ES={es_latest_period} >= config={last_period}）')
    else:
        # ES < config：config 过期，sync 时应以 config 为准重新对齐
        print(f'[日照] ⚠️ ES 落后 config：ES={es_latest_period} < config={last_period}，需检查')


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
        write_status_from_check_output('rizhao', '日照', _output)
    except Exception as _e:
        print(f'⚠️ check_status 失败: {_e}', file=_sys.stderr)

"""rizhao_collector.py - rizhao 默认同步路径（v1.0 SyncRunner 抽象基类化, 2026-07-03）

将 rizhao v0 流式抓取用 gov_price_etl.collectors.base.SyncRunner 重构。
参考 chongqing v0.8（chongqing_collector.py）+ henan v0.8（henan_collector.py）。

设计：
- 继承 SyncRunner
- 重写 _list_work_units()：按 tab × period 扁平化（默认 3 tab × 1 period = 3 units）
- 重写 _process_one()：调 fetch_data.js 流式抓取 → 批量 bulk 写 ES → 落本地进度
- 重写 _on_unit_done()：写 ES progress + 保存本地进度 + 打印汇总
- 重写 _compute_unit_key()：本地进度 key = 'done_<tab>_<period>'

v1.0 字段扩展（道友要求）：
  每个 doc 新增 period_start / period_end / period_days 三个字段。
  业务期格式：'2026-05' → period_start='2026-05-01'、period_end='2026-05-31'、
                            period_days=31（5月有31天）

unit 形状：dict
  {
      'tab_type': '1',                   # 类别 ID（1/2/3）
      'tab_name': '建设工程材料',          # 类别名
      'period': '2026-05',               # 业务期
      'period_start': '2026-05-01',      # v1.0 新增
      'period_end': '2026-05-31',        # v1.0 新增
      'period_days': 31,                 # v1.0 新增
      'period_pages': 109,               # 总页数（preflight 探测）
      'period_total': 1084,              # 总记录数
      'period_unit': '月',                # 周期单位
  }

进度键：
  本地：prog['done_<tab>_<period>'] = True
  ES progress：{run_id}_<tab>_<period> 文档
"""
from __future__ import annotations

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


import calendar
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from typing import Optional, List

# ── ETL 公共依赖 ──
_ETL_PROJECT_ROOT = _resolve_etl_root()
if os.path.isdir(_ETL_PROJECT_ROOT) and _ETL_PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _ETL_PROJECT_ROOT)

from gov_price_etl.collectors.base import (
    LocalProgressStore,
    SyncRunner,
)

# 复用 rizhao v0 的工具（命令行驱动 fetch_data.js）
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import utils as _utils
from utils import (
    TAB_TYPES,
    AREA_CODES,
    CHROME_PATH,
    load_config,
    doc_id,
)


# ─────────────────────────────────────────────────────────────
# 周期窗口解析（v1.0 新增）
# ─────────────────────────────────────────────────────────────

def parse_period_window(period: str) -> dict:
    """解析 '2026-05' / '2026-04' 等业务期号，返回 period 窗口字段。

    Args:
        period: 业务期字符串。日照源站格式：'YYYY-MM'（如 '2026-05'）。

    Returns:
        {
            'period':       原样返回（如 '2026-05'），
            'period_start': 'YYYY-MM-01'，
            'period_end':   'YYYY-MM-DD'（当月最后一天），
            'period_days':  当月天数（28/29/30/31），
            'period_unit':  '月'，
        }
        解析失败时 start/end/days 为空。

    业务规则：
        - period 取 YYYY-MM 作为业务标识（与 _id 幂等性绑定）
        - period_start = 当月第一天
        - period_end = 当月最后一天（calendar.monthrange 推算）
        - period_days = 当月实际天数
    """
    out = {
        'period': period,
        'period_start': '',
        'period_end': '',
        'period_days': 0,
        'period_unit': '月',
    }
    m = re.match(r'^(\d{4})-(\d{1,2})$', (period or '').strip())
    if not m:
        return out
    y, mo = int(m.group(1)), int(m.group(2))
    if not (1 <= mo <= 12):
        return out
    last_day = calendar.monthrange(y, mo)[1]
    out.update(
        period_start=f'{y:04d}-{mo:02d}-01',
        period_end=f'{y:04d}-{mo:02d}-{last_day:02d}',
        period_days=last_day,
    )
    return out


# ─────────────────────────────────────────────────────────────
# fetch_data.js 包装器
# ─────────────────────────────────────────────────────────────

JS_PATH = os.path.join(_SCRIPT_DIR, 'fetch_data.js')

# v1.1 引入 fetch_data.py（Playwright + 内部 fetch API）
from fetch_data import (
    fetch_all as fd_fetch_all,
    fetch_one as fd_fetch_one,
    get_current_period as fd_get_current_period,
    TAB_NAMES as FD_TAB_NAMES,
)


def _run_js(cmd: str, *args, timeout: int = 1800) -> dict:
    """调用 fetch_data.js 子命令，返回解析后的 dict（v0 兼容路径）。"""
    proc = subprocess.run(
        ['node', JS_PATH, cmd] + list(args),
        capture_output=True, text=True,
        cwd=_SCRIPT_DIR,
        timeout=timeout,
        env={**os.environ, 'PATH': os.environ.get('PATH', '')},
    )
    if proc.returncode != 0:
        raise RuntimeError(f"fetch_data.js {cmd} 失败 (rc={proc.returncode}): {proc.stderr[-500:]}")
    return json.loads(proc.stdout)


def get_metadata() -> dict:
    """获取站点元数据：tabs + periods。"""
    return {
        'tabs': [{'name': name, 'id': tid} for tid, name in TAB_TYPES.items()],
        'periods': fd_get_current_period(),
    }


def parse_row(row: dict, period: str, tab_type: str, tab_name: str,
              city: str = '日照市', county: str = '日照市') -> Optional[dict]:
    """将 fetch_data.js stream 模式的 row dict（clmc/ggxh/dw/price/remark）映射成 doc。

    fetch_data.js stream 模式输出每行 JSON：
        rows: [{'index':'1','clmc':'普线','ggxh':'Φ6.5 Q235',
                'dw':'吨','price':'3863.12','remark':''}, ...]

    Returns:
        包含 v1.0 新字段的 dict；row 字段不全返回 None。

    Fields:
        _id                : 幂等键 = MD5(breed+spec+unit+period+price+city+county)
        breed / spec / unit: 材料主字段
        price              : 浮点价格（兼容 ￥/元/数字）
        price_min / max    : 单值时与 price 相等（v4 区间价格式，留口给将来扩展）
        price_range        : 原始字符串
        is_range           : False（单值）
        period             : '2026-05'
        period_start       : '2026-05-01'
        period_end         : '2026-05-31'
        period_days        : 31
        update_date        : period_start 推算
        create_time        : 入库时间
        tab_type / tab_name: 类别标识
        province / city / county: 行政区划（tab=3 时按区县区分）
    """
    if not isinstance(row, dict):
        return None
    clmc = (row.get('clmc') or '').strip()
    if not clmc:
        return None
    spec = (row.get('ggxh') or '').strip()
    unit = (row.get('dw') or '').strip()
    price_raw = (row.get('price') or '').strip()
    remark = (row.get('remark') or '').strip()
    price_clean = re.sub(r'[￥,，元\s]', '', price_raw)
    try:
        price_val = float(price_clean) if price_clean else 0.0
    except Exception:
        price_val = 0.0

    win = parse_period_window(period)
    did = doc_id(clmc, spec, unit, period, price_val, city, county)
    return {
        '_id': did,
        'breed': clmc,
        'spec': spec,
        'unit': unit,
        'price': price_val,
        'price_min': price_val,
        'price_max': price_val,
        'price_range': price_raw,
        'is_range': False,
        'period': period,
        'period_start': win['period_start'],
        'period_end': win['period_end'],
        'period_days': win['period_days'],
        'update_date': win['period_start'] or datetime.now().strftime('%Y-%m-%d'),
        'create_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'province': '山东',
        'city': city,
        'county': county,
        'tab_type': tab_type,
        'tab_name': tab_name,
        'source_index': 'ods_material_rizhao_price',
        'remark': remark,
    }


# ─────────────────────────────────────────────────────────────
# ES 写入
# ─────────────────────────────────────────────────────────────

def ensure_ods_index(es_host: str, es_index: str) -> bool:
    """确保 ODS 索引存在（套用 ETL 共享 mapping，含 period_* 字段）。"""
    from gov_price_etl.indexer import ensure_ods_index as _ensure
    return _ensure(es_host, es_index)


def ensure_progress_index(es_host: str, idx: str) -> bool:
    """确保 progress 索引存在。"""
    from gov_price_etl.indexer import ensure_progress_index as _ensure
    return _ensure(es_host, idx)


def bulk_write(es_host: str, es_index: str, docs: list) -> dict:
    """bulk 写入 ES。返回 {written, failed, errors}。"""
    if not docs:
        return {'written': 0, 'failed': 0, 'errors': []}
    import requests
    bulk = ''
    for d in docs:
        did = d.pop('_id')
        bulk += json.dumps({'index': {'_index': es_index, '_id': did}}, ensure_ascii=False) + '\n'
        bulk += json.dumps(d, ensure_ascii=False) + '\n'
    try:
        resp = requests.post(
            f"{es_host}/_bulk",
            data=bulk.encode('utf-8'),
            headers={'Content-Type': 'application/x-ndjson'},
            timeout=60, verify=False,
        )
        if resp.status_code in (200, 201):
            items = resp.json().get('items', [])
            written = sum(1 for it in items if it.get('index', {}).get('result') in ('created', 'updated'))
            errors = []
            failed = 0
            for it in items:
                err = it.get('index', {}).get('error', {})
                if err:
                    failed += 1
                    errors.append(f"{it['index'].get('_id')}: {err.get('reason', str(err))[:120]}")
            return {'written': written, 'failed': failed, 'errors': errors[:5]}
        return {'written': 0, 'failed': len(docs), 'errors': [f"HTTP {resp.status_code}"]}
    except Exception as e:
        return {'written': 0, 'failed': len(docs), 'errors': [str(e)[:200]]}


# ─────────────────────────────────────────────────────────────
# RizhaoCollector - SyncRunner 化主类
# ─────────────────────────────────────────────────────────────

class RizhaoCollector(SyncRunner):
    """日照工程造价材料采集器（v1.0 SyncRunner 化，2026-07-03）。

    工作单元形状：dict（见模块顶部注释）。

    入口流程（每个 unit）：
        1. 启动 node fetch_data.js stream <tab> <max_pages> 流式抓取
        2. 边抓边解析为 doc（带 period_* 字段）
        3. 攒一批（page_batch_size）后 bulk 写 ES
        4. 完成后写 ES progress + 保存本地进度

    进度隔离：
        本地：done_<tab>_<period> = True（避免重复抓同 tab/期）
        ES progress：<run_id>_<tab>_<period>（一次 run 内有 3 条汇总文档）
    """

    def __init__(
        self,
        cfg: dict,
        run_id: str,
        periods: list[str] = None,
        tabs: list = ('1', '2', '3'),
        max_pages: int = 2000,
        page_batch_size: int = 5,
    ):
        progress_path = os.path.join(
            os.path.dirname(_SCRIPT_DIR),
            '.rizhao_sync_progress.json',
        )
        super().__init__(
            progress=LocalProgressStore(progress_path),
            es_host=cfg['es']['host'],
            es_index=cfg['es']['index'],
            progress_index=cfg['es']['progress_index'],
        )
        self.cfg = cfg
        self.run_id = run_id
        self.tabs = list(tabs)
        # v1.1 多期支持
        self.periods = periods or []  # 空表示自动检测当前期
        self.max_pages = max_pages
        self.page_batch_size = page_batch_size
        self._initialized = False

    # ── SyncRunner 钩子实现 ──

    def _list_work_units(self) -> list[dict]:
        """扁平化所有工作单元：periods × tabs。

        默认：1 当前期 × 3 tab = 3 units。
        多期：N periods × 3 tab = 3N units。
        """
        if not self._initialized:
            self._preflight()

        units = []
        for period in self._periods:
            for tab in self.tabs:
                tab_name = TAB_TYPES.get(tab, tab)
                win = parse_period_window(period)
                key = f"done_{tab}_{win['period']}"
                units.append({
                    'tab_type': tab,
                    'tab_name': tab_name,
                    'period': win['period'],
                    'period_start': win['period_start'],
                    'period_end': win['period_end'],
                    'period_days': win['period_days'],
                    'period_unit': win['period_unit'],
                    '_progress_key': key,
                })
        return units

    def _preflight(self) -> None:
        """初始化：确定期数 + 同步 progress 索引。"""
        # 确保索引存在
        ensure_ods_index(self.es_host, self.es_index)
        ensure_progress_index(self.es_host, self.progress_index)

        if not self.periods:
            # 自动检测当前期
            period = fd_get_current_period()
            self._periods = [period]
            print(f"[✓] 自动探测当前期: {period}")
        else:
            self._periods = list(self.periods)

        # 提示
        for p in self._periods:
            win = parse_period_window(p)
            print(f"[✓] period={p}（{win['period_start']} ~ {win['period_end']}, "
                  f"{win['period_days']} 天）")
        print(f"[✓] 工作 tab: {[TAB_TYPES.get(t, t) for t in self.tabs]}")
        print(f"[✓] 预计 unit 数: {len(self._periods) * len(self.tabs)}")
        self._initialized = True

    def _process_one(self, unit: dict) -> tuple[int, str]:
        """处理单个工作单元：API 抓取（v1.1）→ 写 ES。

        Returns:
            (docs_count, status)，status ∈ {'completed', 'error', 'skipped'}。
        """
        tab_type = unit['tab_type']
        tab_name = unit['tab_name']
        period = unit['period']

        print(f"\n  [▼] tab={tab_name} ({tab_type}) period={period} 抓取中...")

        try:
            # v1.1：直接调 fetch_data.fetch_one（Playwright + 内部 fetch API）
            rows, normalized_period = fd_fetch_one(period, tab_type)
        except Exception as e:
            print(f"  ✗ 抓取失败: {e}")
            return 0, 'error'

        unit['period_total'] = len(rows)
        unit['period_pages'] = 1 if rows else 0

        if not rows:
            print(f"  [skipped] {tab_name} {period}：源站无数据")
            return 0, 'skipped'

        # 构造 docs
        batch = []
        for row in rows:
            d = parse_row(row, period, tab_type, tab_name)
            if d is not None:
                batch.append(d)

        # 一次 bulk 写
        r = bulk_write(self.es_host, self.es_index, batch)
        total_docs_written = r['written']
        total_docs_failed = r['failed']

        print(f"  [{tab_name}] {period} ({unit['period_start']}~{unit['period_end']}, "
              f"{unit['period_days']}天): 抓 {len(rows)} → 写 {total_docs_written} "
              f"(失败 {total_docs_failed})")

        if total_docs_failed > 0 and total_docs_written == 0:
            return total_docs_written, 'error'
        return total_docs_written, 'completed'

    def _on_unit_done(self, unit: dict, docs_count: int, status: str, error: str = '') -> None:
        """完成后：写 ES progress + 保存本地进度 + 打印汇总。"""
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        progress_doc_id = f"{self.run_id}_{unit['tab_type']}_{unit['period']}"

        # v1.0+ 进度百分比：unit 完成即 100%，error 为 0%（dashboard 兜底也会派生）
        total_records = unit.get('period_total', 0) or 0
        if status == 'completed' and total_records > 0:
            percent = round(docs_count / total_records * 100, 2)
        elif status == 'completed':
            percent = 100.0  # 抓到但源站无 total 记录（兜底）
        else:
            percent = 0.0

        # 1. ES progress
        try:
            import requests
            # 字段名映射：progress mapping 是 dynamic=strict，复用现有字段
            progress_doc = {
                'run_id': self.run_id,
                'tab_type': unit['tab_type'],
                'tab_name': unit['tab_name'],
                'period': unit['period'],
                'period_start': unit['period_start'],
                'period_end': unit['period_end'],
                'period_days': unit['period_days'],
                'total_records': total_records,
                'total_pages': unit.get('period_pages', 0),
                'docs_written': docs_count,
                'percent': percent,
                'status': 'completed' if status == 'completed' else 'error',
                'error': error,
                'created_at': now,
                'last_updated': now,
            }
            requests.put(
                f"{self.es_host}/{self.progress_index}/_doc/{progress_doc_id}",
                json=progress_doc, timeout=15, verify=False,
            )
        except Exception as e:
            print(f"  ⚠ 写 ES progress 失败: {e}")

        # 2. 本地进度
        prog = self.progress.load()
        key = unit['_progress_key']
        prog[key] = {
            'tab_type': unit['tab_type'],
            'tab_name': unit['tab_name'],
            'period': unit['period'],
            'period_start': unit['period_start'],
            'period_end': unit['period_end'],
            'period_days': unit['period_days'],
            'period_total': unit.get('period_total', 0),
            'period_pages': unit.get('period_pages', 0),
            'docs_written': docs_count,
            'status': 'ok' if status == 'completed' else 'error',
            'error': error,
            'created_at': now,
        }
        self.progress.save(prog)

        icon = '✓' if status == 'completed' else '✗'
        print(
            f"  [{icon}] {unit['tab_name']} ({unit['period']}, "
            f"{unit['period_start']}~{unit['period_end']}, "
            f"{unit['period_days']}天): {docs_count} 条 → {status}"
        )

    def _compute_unit_key(self, unit: dict) -> str:
        """本地进度 key = 'done_<tab>_<period>'。"""
        return unit['_progress_key']


# ─────────────────────────────────────────────────────────────
# 工厂方法
# ─────────────────────────────────────────────────────────────

def make_collector(
    cfg_path: str,
    run_id: str,
    periods: Optional[List[str]] = None,
    tabs: Optional[List[str]] = None,
    max_pages: int = 2000,
    page_batch_size: int = 5,
) -> RizhaoCollector:
    """从 config.yml 构造 RizhaoCollector。

    用法（sync.py 默认路径）：
        cfg = load_config(cfg_path)
        collector = make_collector(cfg_path, run_id, periods=['2026-01', '2026-02'])
        result = collector.run()
    """
    cfg = load_config(cfg_path)
    return RizhaoCollector(
        cfg=cfg,
        run_id=run_id,
        periods=periods,
        tabs=tabs or ['1', '2', '3'],
        max_pages=max_pages,
        page_batch_size=page_batch_size,
    )
"""ningxia_collector.py - 宁夏工程造价信息采集器（v0.8, 2026-07-03）

将 ningxia v3 的 sync.py 主流程用 gov_price_etl.collectors.base.SyncRunner 重构。
参考 chongqing v0.9 试点（chongqing_collector.py）+ huhehaote v0.8
（huhehaote_collector.py）+ hunan v0.8（hunan_collector.py）。

设计：
- 继承 SyncRunner
- 重写 _list_work_units()：抓 6 页列表 → 过滤 year + journal_keyword →
  排除已 done → 计算 period 窗口 → return list[dict]
- 重写 _process_one(unit)：抓详情 → 下载 PDF → MinIO → 解析 →
  bulk_index（含 period_start/end/days）
- 重写 _on_unit_done()：写 ES progress + 本地进度
- 重写 _compute_unit_key()：unit['detail_url']

v0.8 字段扩展（道友要求）：
  必含 period / period_start / period_end / period_days（缺一不可）
  - 双月刊：第 N 期 → 覆盖 (N-1)*2+1 月 至 N*2 月
    例：第2期 → 2026-03-01 ~ 2026-04-30（61 天）

unit 形状（dict）：
  {
    'period': '2026.第2期',
    'period_num': 2,                       # 第几期
    'year': 2026,
    'title': '...',
    'publish_date': '2026-05-18',          # 从 list time 标签抽
    'detail_url': 'https://jst.nx.gov.cn/...',
    'pdf_url': '',                          # _process_one 中从详情页抽
    'minio_key': '',
    'period_start': '2026-03-01',
    'period_end': '2026-04-30',
    'period_days': 61,
  }
"""
from __future__ import annotations

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


import calendar
import os
import re
import sys
import tempfile
import time
from datetime import date, datetime
from typing import Optional

# ── ETL 公共依赖 ──
_ETL_PROJECT_ROOT = _resolve_etl_root()
if _ETL_PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _ETL_PROJECT_ROOT)

from gov_price_etl.collectors.base import (
    LocalProgressStore,
    SyncRunner,
)

# 复用 v3 sync_v3_legacy.py 的解析逻辑（PDF 解析、列表解析、详情页）
# 注：sync.py 是新 CLI 入口（4 行），不能直接 import sync，要走 sync_legacy 别名
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
import sync_legacy as _legacy  # parse_list_page, fetch_all_periods, fetch_detail_pdf, pdf_basename, parse_pdf, bulk_index, _doc_id
import utils as _utils  # load_config, get_es_client, get_s3_client, ensure_bucket, ensure_ods_index, ensure_progress_index


# ─────────────────────────────────────────────────────────────
# 业务期号 (period) + period 窗口解析（v0.8 新增）
# ─────────────────────────────────────────────────────────────

# 中文数字 → 阿拉伯数字（1..10）
_CN_NUM = {
    '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
    '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
}


def _cn_to_int(s: str) -> int:
    """'一' / '十一' / '二十三' → 整数（百以内常用）"""
    if not s:
        return 0
    s = s.strip()
    if s.isdigit():
        return int(s)
    if s in _CN_NUM:
        return _CN_NUM[s]
    if s.startswith('十'):
        rest = s[1:]
        return 10 + (_CN_NUM.get(rest, 0) if rest else 0)
    if '十' in s:
        a, _, b = s.partition('十')
        return _CN_NUM.get(a, 0) * 10 + _CN_NUM.get(b, 0)
    return 0


def _last_day(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def parse_period_label(title: str) -> tuple[str, int, int]:
    """从 title 提取 (period, year, issue_num)

    title 模式：
      - '关于发布2026年第2期《宁夏工程造价》的通知'  → ('2026.第2期', 2026, 2)
      - '《宁夏工程造价》（2023年第6期 总第150期）'   → ('2023.第6期', 2023, 6)

    Returns:
        (period_label, year, issue_num)
        解析失败 → (title[:30], 0, 0)
    """
    if not title:
        return ('', 0, 0)
    # 模式 A：'2026年第2期'
    m = re.search(r'(\d{4})\s*年第\s*([一二三四五六七八九十\d]+)\s*期', title)
    if m:
        y = int(m.group(1))
        n = _cn_to_int(m.group(2))
        return (f'{y}.第{n}期', y, n)
    return (title[:30], 0, 0)


def parse_period_window_from_issue(year: int, issue_num: int) -> dict:
    """双月刊：第 N 期 → 覆盖 (N-1)*2+1 月 至 N*2 月

    例：
      - 2026 第 1 期 → 2026-01-01 ~ 2026-02-28 (59 天)
      - 2026 第 2 期 → 2026-03-01 ~ 2026-04-30 (61 天)
      - 2026 第 6 期 → 2026-11-01 ~ 2026-12-31 (61 天)

    兜底：若 issue_num 越界（0 或 > 12），返回空窗口。
    """
    if issue_num < 1 or issue_num > 12 or year < 1900:
        return {
            'period_start': '',
            'period_end': '',
            'period_days': 0,
        }
    start_month = (issue_num - 1) * 2 + 1
    end_month = issue_num * 2
    period_start = f'{year:04d}-{start_month:02d}-01'
    period_end = f'{year:04d}-{end_month:02d}-{_last_day(year, end_month):02d}'
    period_days = sum(_last_day(year, m) for m in range(start_month, end_month + 1))
    return {
        'period_start': period_start,
        'period_end': period_end,
        'period_days': period_days,
    }


def compute_period_window_from_title(title: str) -> dict:
    """统一入口：从 title 算 period 窗口"""
    _, year, issue_num = parse_period_label(title)
    return parse_period_window_from_issue(year, issue_num)


# ─────────────────────────────────────────────────────────────
# NingxiaCollector - 宁夏 SyncRunner 化主类
# ─────────────────────────────────────────────────────────────

class NingxiaCollector(SyncRunner):
    """宁夏工程造价信息采集器（v0.8 SyncRunner 化）。

    工作单元形状：dict（含 period 业务期号、URL、PDF URL 占位、period 窗口等）
    """

    def __init__(
        self,
        cfg: dict,
        year: int,
        run_id: str,
    ):
        progress_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            '.ningxia_sync_progress.json',
        )
        super().__init__(
            progress=LocalProgressStore(progress_path),
            es_host=cfg['es']['host'],
            es_index=cfg['es']['ods_index'],
            progress_index=cfg['es']['progress_index'],
        )
        self.cfg = cfg
        self.year = year
        self.run_id = run_id
        # es / s3 客户端懒加载
        self._es = None
        self._s3 = None
        # 一次性 setup（确保 ODS / progress 索引存在）
        self._ensure_indices()

    def _ensure_indices(self) -> None:
        """确保 ES ODS / progress 索引存在（幂等）"""
        _utils.ensure_bucket(self.s3, self.cfg['minio']['bucket'])
        _utils.ensure_ods_index(self.es, self.es_host, self.es_index)
        _utils.ensure_progress_index(self.es, self.progress_index)

    # ── 客户端懒加载 ──

    @property
    def es(self):
        if self._es is None:
            self._es = _utils.get_es_client(self.es_host)
        return self._es

    @property
    def s3(self):
        if self._s3 is None:
            self._s3 = _utils.get_s3_client(self.cfg)
        return self._s3

    # ── SyncRunner 钩子实现 ──

    def _list_work_units(self) -> list[dict]:
        """抓 6 页列表 → 过滤 year + journal_keyword → 计算 period 窗口 → 排除已 done

        注：LocalProgressStore.is_done 只查平铺 key，所以这里在返 list 前先
        加载本地 + ES 进度，手动过滤掉 status='ok' 的 unit。
        """
        items = _legacy.fetch_all_periods(self.cfg)
        journal_kw = self.cfg.get('journal_keyword', '')

        todo = []
        for it in items:
            if journal_kw and journal_kw not in it['title']:
                continue
            if f'{self.year}年' not in it['title']:
                continue
            period_label, year, issue_num = parse_period_label(it['title'])
            if year == 0 or issue_num == 0:
                print(f'  [skip] {it["title"]}: 解析 period 失败')
                continue
            w = parse_period_window_from_issue(year, issue_num)
            unit = {
                'period': period_label,
                'period_num': issue_num,
                'year': year,
                'title': it['title'],
                'publish_date': it['publish_date'],
                'detail_url': it['detail_url'],
                'pdf_url': '',
                'minio_key': '',
                'period_start': w['period_start'],
                'period_end': w['period_end'],
                'period_days': w['period_days'],
            }
            todo.append(unit)
        # 按期号排序（让 progress 输出稳定）
        todo.sort(key=lambda u: (u['year'], u['period_num']))

        # 过滤已 done（progress 文件是嵌套 {"done": {url: ...}} 结构）
        done_map = self.progress.load().get('done', {})
        before = len(todo)
        todo = [u for u in todo if (done_map.get(u['detail_url'], {}).get('status') not in ('ok', 'completed', 'partial'))]
        skipped = before - len(todo)
        if skipped:
            print(f'  [progress] 跳过 {skipped} 个已 done 的工作单元（status=ok）')
        return todo

    def _process_one(self, unit: dict) -> tuple[int, str]:
        """处理单个工作单元：抓详情 → PDF → MinIO → 解析 → bulk_index

        Returns:
            (docs_count, status)，status ∈ {'completed', 'error', 'skipped'}。
        """
        # 1. 抓详情页抽 PDF URL
        try:
            pdf_title, pdf_url, _ = _legacy.fetch_detail_pdf(self.cfg, unit['detail_url'])
        except Exception as e:
            print(f"  ✗ 抓详情页失败: {e}")
            return 0, "error"
        if not pdf_url:
            print(f"  ✗ 详情页无 PDF 链接")
            return 0, "error"
        unit['pdf_url'] = pdf_url

        # 2. 下载 PDF（先下到 tmp）
        with tempfile.TemporaryDirectory() as tmpdir:
            local_pdf = os.path.join(tmpdir, 'source.pdf')
            try:
                from gov_price_etl.collectors import download_file
                download_file(pdf_url, local_pdf, timeout=600)
            except Exception as e:
                print(f"  ✗ 下载 PDF 失败: {e}")
                return 0, "error"

            # 3. 上传 MinIO（如果未上传）
            basename = _legacy.pdf_basename(pdf_url)
            minio_key = f"{self.cfg['minio']['prefix']}/{unit['period']}/{basename}"
            try:
                if not self._minio_exists(self.cfg['minio']['bucket'], minio_key):
                    from gov_price_etl.collectors import upload_to_minio
                    upload_to_minio(self.s3, self.cfg['minio']['bucket'], minio_key, local_pdf)
            except Exception as e:
                print(f"  ✗ 上传 MinIO 失败: {e}")
                return 0, "error"
            unit['minio_key'] = minio_key

            # 4. PDF 解析 → 长表
            try:
                rows = _legacy.parse_pdf(local_pdf)
            except Exception as e:
                print(f"  ✗ PDF 解析失败: {e}")
                return 0, "error"

            if not rows:
                print(f"  [skipped] {unit['period']}：PDF 解析无数据")
                return 0, "skipped"

            # 5. 转 ES doc 列表（带 period_start/end/days）
            docs = self._build_docs(
                rows,
                period=unit['period'],
                period_start=unit['period_start'],
                period_end=unit['period_end'],
                period_days=unit['period_days'],
                publish_date=unit.get('publish_date', ''),
                minio_key=minio_key,
                source_url=pdf_url,
            )
            ok, err = _legacy.bulk_index(self.es, self.es_index, docs)
            if err:
                print(f"  ✗ bulk_index 失败: {ok} ok, {err} err")
                return ok, "error"
            return ok, "completed"

    def _on_unit_done(self, unit, docs_count: int, status: str, error: str = "") -> None:
        """完成后：写 ES progress + 本地进度 + 打印"""
        now = datetime.now().isoformat(timespec='seconds')
        # 本地进度（嵌套结构）
        progress = self.progress.load()
        progress.setdefault('done', {})
        progress['done'][unit['detail_url']] = {
            'period': unit['period'],
            'period_start': unit['period_start'],
            'period_end': unit['period_end'],
            'period_days': unit['period_days'],
            'publish_date': unit.get('publish_date', ''),
            'detail_url': unit['detail_url'],
            'pdf_url': unit.get('pdf_url', ''),
            'minio_key': unit.get('minio_key', ''),
            'docs_written': docs_count,
            'status': status,
            'error': error,
            'created_at': now,
        }
        self.progress.save(progress)

        # ES progress
        try:
            self.es.index(index=self.progress_index, body={
                'period': unit['period'],
                'period_start': unit['period_start'],
                'period_end': unit['period_end'],
                'period_days': unit['period_days'],
                'publish_date': unit.get('publish_date', ''),
                'detail_url': unit['detail_url'],
                'pdf_url': unit.get('pdf_url', ''),
                'minio_key': unit.get('minio_key', ''),
                'docs_written': docs_count,
                'status': status,
                'error': error,
                'created_at': now,
            })
        except Exception as e:
            print(f"  ⚠ 写 ES progress 失败: {e}")

        icon = {'completed': '✓', 'error': '✗', 'skipped': '⊘'}.get(status, '?')
        win = f"{unit['period_start']} ~ {unit['period_end']} ({unit['period_days']}d)" if unit['period_start'] else 'window=∅'
        print(f"  [{icon}] {unit['period']:14s} {win:42s} docs={docs_count:5d} ({status})")

    def _compute_unit_key(self, unit) -> str:
        """本地进度 key：unit['detail_url']

        注：LocalProgressStore.is_done 只查平铺 key，进度文件用嵌套 {"done": {url: ...}} 结构，
        在 _list_work_units 已经预过滤。这里返回 url 给基类用，避免 key 冲突。
        """
        return f'nx:{unit["detail_url"]}'

    # ── 私有方法 ──

    def _minio_exists(self, bucket: str, key: str) -> bool:
        """检查 MinIO 对象是否存在（避免重复上传）"""
        try:
            self.s3.head_object(Bucket=bucket, Key=key)
            return True
        except Exception:
            return False

    def _build_docs(self, rows, period, period_start, period_end, period_days,
                    publish_date, minio_key, source_url):
        """从 PDF 解析出来的 row 列表生成 ES doc 列表，注入 period_start/end/days

        与原 sync.py 主流程的 doc 构造等价，但字段扩展了 period 窗口。
        同时写入 publish_date（宁夏特有）和 update_date（标准 mapping 字段，两者一致）。
        """
        now = datetime.now().isoformat(timespec='seconds')
        docs = []
        for r in rows:
            docs.append({
                'no': r['no'],
                'breed': r['breed'],
                'spec': r['spec'],
                'unit': r['unit'],
                'price': r['price'],
                'tax_price': r['tax_price'],
                'remark': r.get('remark', ''),
                'section': r['section'],
                'category': r['category'],
                'region': r.get('region', ''),
                'city': r.get('city', ''),
                'period': period,
                'period_start': period_start,
                'period_end': period_end,
                'period_days': period_days,
                'province': '宁夏',
                'publish_date': publish_date,
                'update_date': publish_date,  # 与 publish_date 一致，供 check.py update_date sort 用
                'create_time': now,
                'source_pdf': minio_key,
                'source_url': source_url,
            })
        return docs


# ─────────────────────────────────────────────────────────────
# 工厂方法
# ─────────────────────────────────────────────────────────────

def make_collector(cfg_path: str, year: int, run_id: str) -> NingxiaCollector:
    """从 config.yml 构造 NingxiaCollector。

    Args:
        cfg_path: config.yml 绝对路径
        year: 同步年份（如 2026）
        run_id: 本次运行标识
    """
    cfg = _utils.load_config()
    return NingxiaCollector(
        cfg=cfg,
        year=year,
        run_id=run_id,
    )

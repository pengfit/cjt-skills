"""jiangxi_collector.py - 江西建设工程材料价格采集器（v0.9, 2026-07-03）

将 jiangxi v0.8 的 sync.py 主流程用 gov_price_etl.collectors.base.SyncRunner 重构。
参考 chongqing v0.8 试点（chongqing_collector.py）+ hunan v0.8
（hunan_collector.py）+ huhehaote v0.8（huhehaote_collector.py）。

设计：
- 继承 SyncRunner
- 重写 _list_work_units()：列表页 articleList JSON → 过滤 journal_keyword +
  year → 排除已 done → 计算 period 窗口（按 publish_date 所在月）
- 重写 _process_one(unit)：下载 PDF → MinIO → pdfplumber 解析 → bulk_index
- 重写 _on_unit_done()：写 ES progress + 本地进度
- 重写 _compute_unit_key()：unit['id']（articleList ID，幂等去重）

v0.9 字段扩展（道友要求）：
  必含 period / period_start / period_end / period_days（缺一不可）
  - period 业务期号：'2026.第5期'（从 title 抽）
  - period 窗口：按 publish_date 所在月
      publish_date=2026-06-05 → period_start=2026-06-01, period_end=2026-06-30, period_days=30
  - 备选兜底：若 title 含"X-Y月份"则按月区间算（江西期刊暂无此模式，留扩展位）

unit 形状（dict）：
  {
    'id': '2062796646723690496',      # articleList ID，幂等 key
    'period': '2026.第5期',
    'title': '江西省材料价格参考信息2026年第5期',
    'publish_date': '2026-06-05',
    'pdf_url': 'http://.../iGNhYG0T.pdf',
    'detail_url': 'https://.../content/content_xxx.html',
    'minio_key': 'jiangxi-price/2026.第5期/iGNhYG0T.pdf',
    'period_start': '2026-06-01',
    'period_end':   '2026-06-30',
    'period_days':  30,
  }
"""
from __future__ import annotations

import calendar
import os
import re
import sys
import tempfile
import time
from datetime import date, datetime
from typing import Optional

# ── ETL 公共依赖 ──
_ETL_PROJECT_ROOT = "/Users/pengfit/.openclaw/workspace/skills/gov-price-etl"
if _ETL_PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _ETL_PROJECT_ROOT)

from gov_price_etl.collectors.base import (
    LocalProgressStore,
    SyncRunner,
)
from gov_price_etl.collectors import (
    fetch_html,
    download_file,
    upload_to_minio,
)

# 复用 v0.8 sync.py 的列表/解析工具
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
import sync as _legacy  # fetch_all_periods, parse_pdf, pdf_basename, bulk_index, _doc_id, ARTICLE_LIST_RE
import utils as _utils   # load_config, get_es_client, get_s3_client, ensure_bucket, ensure_ods_index, ensure_progress_index


# ─────────────────────────────────────────────────────────────
# period 窗口解析（v0.9 新增，道友要求字段不能缺）
# ─────────────────────────────────────────────────────────────

def _last_day(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def parse_period_window(publish_date: str, title: str = '') -> dict:
    """江西期刊的 period 窗口解析。

    江西《江西省材料价格参考信息》是月刊，列表页只给 publish_date（如 '2026-06-05'），
    PDF 内部不含"适用时间"字段，所以按 publish_date 所在月作为 period 窗口。

    模式 A（默认）：按 publish_date 所在月
        publish_date='2026-06-05' → (2026-06-01, 2026-06-30, 30)
    模式 B（兜底/未来扩展）：title 含 'X-Y月份' 时按月区间
        '2026年第1期（1-2月份）...' → (2026-01-01, 2026-02-28, 59)
        注：当前江西期刊 title 不含此模式，留扩展位。

    Returns:
        {'period_start': 'YYYY-MM-DD', 'period_end': 'YYYY-MM-DD', 'period_days': int}
    """
    # 模式 B（兜底）：title 含 "X-Y月份"
    if title:
        m = re.search(r'(\d{1,2})\s*[-–—~]\s*(\d{1,2})\s*月份?', title)
        if m:
            # 从 publish_date 取年份
            ym = re.search(r'(\d{4})', publish_date or '')
            y = int(ym.group(1)) if ym else datetime.now().year
            m1, m2 = int(m.group(1)), int(m.group(2))
            if 1 <= m1 <= 12 and 1 <= m2 <= 12 and m1 <= m2:
                period_start = f'{y:04d}-{m1:02d}-01'
                period_end = f'{y:04d}-{m2:02d}-{_last_day(y, m2):02d}'
                period_days = sum(_last_day(y, m) for m in range(m1, m2 + 1))
                return {
                    'period_start': period_start,
                    'period_end': period_end,
                    'period_days': period_days,
                }

    # 模式 A（默认）：publish_date 所在月
    if not publish_date:
        return _empty_window()
    try:
        y, mo, _ = publish_date.split('-')
        y, mo = int(y), int(mo)
        if not (1 <= mo <= 12):
            return _empty_window()
        ds = date(y, mo, 1)
        de = date(y, mo, _last_day(y, mo))
        return {
            'period_start': ds.isoformat(),
            'period_end': de.isoformat(),
            'period_days': (de - ds).days + 1,
        }
    except Exception:
        return _empty_window()


def _empty_window() -> dict:
    return {
        'period_start': '',
        'period_end': '',
        'period_days': 0,
    }


# ─────────────────────────────────────────────────────────────
# 业务期号 (period) 解析
# ─────────────────────────────────────────────────────────────

def parse_period_label(title: str) -> str:
    """从 title 提取 period 业务期号。

    title 模式：'江西省材料价格参考信息2026年第5期'
                       → '2026.第5期'
    """
    if not title:
        return ''
    m = re.search(r'(\d{4})\s*年\s*第\s*(\d+)\s*期', title)
    if m:
        return f'{m.group(1)}.第{m.group(2)}期'
    # 兜底：截前 30 字
    return title[:30]


# ─────────────────────────────────────────────────────────────
# JiangxiCollector - 江西 SyncRunner 化主类
# ─────────────────────────────────────────────────────────────

class JiangxiCollector(SyncRunner):
    """江西建设工程材料价格采集器（v0.9 SyncRunner 化）。

    工作单元形状：dict（含 period 业务期号、articleList ID、PDF URL 等）
    """

    def __init__(
        self,
        cfg: dict,
        year: int,
        run_id: str,
    ):
        progress_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            '.jiangxi_sync_progress.json',
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

    def _list_work_units(self) -> list:
        """列表 articleList → 过滤 journal_keyword + year → 计算 period 窗口 → 排除已 done

        注：LocalProgressStore.is_done 只查平铺 key，jiangxi 进度文件用嵌套
        {"done": {id: {...}}} 结构，所以这里在返 list 前先加载本地进度，
        手动过滤掉 status='ok' 的 unit。
        """
        items = _legacy.fetch_all_periods(self.cfg)
        journal_kw = self.cfg.get('journal_keyword', '')
        # 过滤：journal_keyword + year + 有 pdf_url
        todo = []
        for it in items:
            if journal_kw and journal_kw not in it['title']:
                continue
            if f'{self.year}年' not in it['title']:
                continue
            if not it.get('pdf_url'):
                continue
            period = parse_period_label(it['title'])
            w = parse_period_window(it.get('publish_date', ''), it.get('title', ''))
            unit = {
                'id': it['id'],
                'period': period,
                'title': it['title'],
                'publish_date': it.get('publish_date', ''),
                'pdf_url': it['pdf_url'],
                'detail_url': it.get('detail_url', ''),
                'minio_key': '',
                'period_start': w['period_start'],
                'period_end': w['period_end'],
                'period_days': w['period_days'],
            }
            todo.append(unit)
        # 按期号排序（让 progress 输出稳定，第1期→第5期）
        todo.sort(key=lambda u: u['period'])

        # 过滤已 done（status=ok/partial 跳过；failed 也跳过避免重复失败）
        done_map = self.progress.load().get('done', {})
        before = len(todo)
        todo = [
            u for u in todo
            if (done_map.get(u['id'], {}).get('status') not in ('ok', 'completed', 'partial'))
        ]
        skipped = before - len(todo)
        if skipped:
            print(f'  [progress] 跳过 {skipped} 个已 done 的工作单元（status=ok/partial）')
        return todo

    def _process_one(self, unit: dict) -> tuple[int, str]:
        """处理单个工作单元：下载 PDF → MinIO → pdfplumber 解析 → bulk_index

        Returns:
            (docs_count, status)，status ∈ {'completed', 'error', 'skipped'}。
        """
        period = unit['period']
        pdf_url = unit['pdf_url']

        # 1. 下载 PDF（先下到 tmp）
        with tempfile.TemporaryDirectory() as tmpdir:
            local_pdf = os.path.join(tmpdir, 'source.pdf')
            try:
                _legacy.download_file(pdf_url, local_pdf, timeout=600)
            except Exception as e:
                print(f"  ✗ 下载 PDF 失败: {e}")
                return 0, "error"

            # 2. 上传 MinIO（如果未上传）
            basename = _legacy.pdf_basename(pdf_url)
            minio_key = f"{self.cfg['minio']['prefix']}/{period}/{basename}"
            try:
                if not self._minio_exists(self.cfg['minio']['bucket'], minio_key):
                    _legacy.upload_to_minio(self.s3, self.cfg['minio']['bucket'], minio_key, local_pdf)
            except Exception as e:
                print(f"  ✗ 上传 MinIO 失败: {e}")
                return 0, "error"
            unit['minio_key'] = minio_key

            # 3. PDF 解析 → 长表
            try:
                rows = _legacy.parse_pdf(local_pdf)
            except Exception as e:
                print(f"  ✗ PDF 解析失败: {e}")
                return 0, "error"

            if not rows:
                print(f"  [skipped] {period}：PDF 解析无数据")
                return 0, "skipped"

            # 4. 转 ES doc 列表（带 period_start/end/days）
            docs = _new_docs_for_es(
                rows, period,
                unit['period_start'], unit['period_end'], unit['period_days'],
                minio_key, pdf_url, unit.get('publish_date', ''),
            )

            # 5. bulk_index（按 _id 幂等）
            ok, err = _legacy.bulk_index(self.es, self.es_index, docs)
            if err:
                print(f"  ✗ bulk_index 失败: {ok} ok, {err} err")
                return ok, "error"
            return ok, "completed"

    def _on_unit_done(self, unit, docs_count: int, status: str, error: str = "") -> None:
        """完成后：写 ES progress + 本地进度 + 打印"""
        now = datetime.now().isoformat(timespec='seconds')
        # 本地进度（嵌套结构 {"done": {id: {...}}}）
        progress = self.progress.load()
        progress.setdefault('done', {})
        progress['done'][unit['id']] = {
            'period': unit['period'],
            'period_start': unit['period_start'],
            'period_end': unit['period_end'],
            'period_days': unit['period_days'],
            'publish_date': unit.get('publish_date', ''),
            'detail_url': unit.get('detail_url', ''),
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
                'detail_url': unit.get('detail_url', ''),
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
        print(f"  [{icon}] {unit['period']:14s} {win:40s}  docs={docs_count:5d}  ({status})")

    def _compute_unit_key(self, unit) -> str:
        """本地进度 key：'jx:' 前缀 + unit['id']（articleList ID，幂等去重）"""
        return f'jx:{unit["id"]}'

    # ── 私有方法 ──

    def _minio_exists(self, bucket: str, key: str) -> bool:
        """检查 MinIO 对象是否存在（避免重复上传）"""
        try:
            self.s3.head_object(Bucket=bucket, Key=key)
            return True
        except Exception:
            return False


# ─────────────────────────────────────────────────────────────
# 工厂方法
# ─────────────────────────────────────────────────────────────

def make_collector(cfg_path: str, year: int, run_id: str) -> JiangxiCollector:
    """从 config.yml 构造 JiangxiCollector。

    Args:
        cfg_path: config.yml 绝对路径（保留兼容位，实际从 utils.load_config() 读）
        year: 同步年份（如 2026）
        run_id: 本次运行标识
    """
    cfg = _utils.load_config()
    return JiangxiCollector(
        cfg=cfg,
        year=year,
        run_id=run_id,
    )


# ─────────────────────────────────────────────────────────────
# doc 生成器（带 period 字段注入）
# ─────────────────────────────────────────────────────────────

def _new_docs_for_es(
    rows, period, period_start, period_end, period_days,
    minio_key, pdf_url, publish_date='',
):
    """从 parse 出来的 row 列表生成 ES doc 列表，注入 period_start/end/days

    Args:
        rows: parse_pdf() 返回的 row 列表
        period: 业务期号（'2026.第5期'）
        period_start: 'YYYY-MM-DD'
        period_end:   'YYYY-MM-DD'
        period_days:  int
        minio_key: MinIO 对象 key
        pdf_url: PDF 源 URL
        publish_date: 发布日期 YYYY-MM-DD
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
            'category': r.get('category', ''),
            'section': r['section'],
            'region': r.get('region', ''),
            'city': r.get('city', ''),
            'vat_rate': r.get('vat_rate'),
            'price_kind': '含税',  # PDF 给的是含税价
            'period': period,
            'period_start': period_start,
            'period_end': period_end,
            'period_days': period_days,
            'province': '江西',
            'update_date': publish_date,
            'create_time': now,
            'source_pdf': minio_key,
            'source_url': pdf_url,
        })
    return docs
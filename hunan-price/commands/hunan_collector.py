"""hunan_collector.py - 湖南建设工程材料价格行情采集器（v0.8, 2026-07-03）

将 hunan v3 的 sync.py 主流程用 gov_price_etl.collectors.base.SyncRunner 重构。
参考 chongqing v0.8 试点（chongqing_collector.py）+ huhehaote v0.8
（huhehaote_collector.py）+ henan v0.8（henan_collector.py）。

设计：
- 继承 SyncRunner
- 重写 _list_work_units()：抓 14 页列表 → 过滤 year/journal_keywords →
  排除已 done → 计算 period 窗口（行情资讯走 title，行情表走 PDF 编制说明
  适用时间） → return list[dict]
- 重写 _process_one(unit)：抓详情 → 下载 PDF → MinIO → 解析 适用时间 →
  pdfplumber 解析 → bulk_index（含 period_start/end/days）
- 重写 _on_unit_done()：写 ES progress + 本地进度
- 重写 _compute_unit_key()：unit['detail_url']

v0.8 字段扩展（道友要求）：
  必含 period / period_start / period_end / period_days（缺一不可）
  - 行情资讯：从 title 抽 (M1-M2月份) → (Y, M1, 1) ~ (Y, M2, last_day)
  - 行情表：从 PDF 首页"编制说明"第 3 条"适用时间：YYYY年M月D日-M月D日" regex
    （半月刊；上半/月 1-15 日，下半月 16-末日 之类，由 PDF 给出）
  - 兜底：URL YYYYMM → 当月窗口

unit 形状（dict）：
  {
    'period': '2026.第1期(行情资讯)' | '2026.第1期(行情表)',
    'period_kind': 'zixun' | 'hangqingbiao',
    'title': '...',
    'publish_date': '2026-03-19',     # 从 URL 文件名 tYYYYMMDD
    'detail_url': 'https://zjt.hunan.gov.cn/.../t20260319_33937465.html',
    'pdf_url': '',                     # _process_one 中从详情页抽
    'minio_key': '',
    'period_start': '',                # _process_one 中从 PDF 抽
    'period_end': '',
    'period_days': 0,
  }
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
import os
import re
import sys
import tempfile
import time
from datetime import date, datetime
from typing import Optional
from urllib.parse import urljoin, urlparse

# ── ETL 公共依赖 ──
_ETL_PROJECT_ROOT = _resolve_etl_root()
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

# 复用 v0.x sync.py 的解析逻辑（PDF 解析、列表解析）
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
import sync as _legacy  # fetch_all_periods, fetch_detail_pdf, parse_zixun_pdf, parse_half_month_table, _detect_period_kind, _parse_price, _parse_rate, _parse_index, _clean_cell, HALF_MONTH_MATERIALS, bulk_index, _doc_id, pdf_basename, PROGRESS_FILE
from sync import _new_docs_for_es  # 注入 period_start/end/days 的 doc 生成器
import utils as _utils   # load_config, get_es_client, get_s3_client, ensure_bucket


# ─────────────────────────────────────────────────────────────
# period 窗口解析（v0.8 新增）
# ─────────────────────────────────────────────────────────────

# 中文数字 → 阿拉伯数字
_CN_NUM = {
    '一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
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


def parse_period_window_zixun(title: str) -> dict:
    """行情资讯：从 title 抽 (M1-M2月份) → period 窗口

    title 模式：'2026年第一期（1-2月份）湖南省建设工程材料价格行情资讯'
    """
    if not title:
        return _empty_window()
    # 模式 1：'2026年第一期（1-2月份）' 或 '2026年第1期(3-4月份)'
    m = re.search(r'(\d{4})\s*年\s*第?([一二三四五六七八九十\d]+)期[（(]\s*(\d{1,2})\s*[-–—~]\s*(\d{1,2})\s*月份?\s*[）)]', title)
    if m:
        y = int(m.group(1))
        m1, m2 = int(m.group(3)), int(m.group(4))
        n = _cn_to_int(m.group(2))
        period = f'{y}.第{n}期(行情资讯)' if n else f'{y}.?(行情资讯)'
        period_start = f'{y:04d}-{m1:02d}-01'
        period_end = f'{y:04d}-{m2:02d}-{_last_day(y, m2):02d}'
        period_days = sum(_last_day(y, m) for m in range(m1, m2 + 1))
        return {
            'period': period,
            'period_start': period_start,
            'period_end': period_end,
            'period_days': period_days,
        }
    return _empty_window()


def parse_period_window_hangqingbiao_from_pdf(pdf_path: str) -> dict:
    """行情表：从 PDF 首页"编制说明"第 3 条"适用时间" → period 窗口

    权威源：PDF 编制说明第 3 条文字（半月刊，每半月 1 期，PDF 明确写出起止日期）。
    例：'适用时间：2026年1月1日-1月15日。' → (2026-01-01, 2026-01-15)
    """
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            text = pdf.pages[0].extract_text() or ''
    except Exception:
        return _empty_window()
    # 模式 A：同年内 'YYYY年M月D日-M月D日'（半月刊常见）
    m = re.search(r'适用时间[：:]\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*[-–—~]\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日', text)
    if m:
        y, m1, d1, m2, d2 = [int(g) for g in m.groups()]
        ds = date(y, m1, d1)
        de = date(y, m2, d2)
        return {
            'period_start': ds.isoformat(),
            'period_end': de.isoformat(),
            'period_days': (de - ds).days + 1,
        }
    # 模式 B：跨年 'YYYY年M月D日-YYYY年M月D日'（罕见，留兜底）
    m = re.search(r'适用时间[：:]\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*[-–—~]\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日', text)
    if m:
        y1, m1, d1, y2, m2, d2 = [int(g) for g in m.groups()]
        ds = date(y1, m1, d1)
        de = date(y2, m2, d2)
        return {
            'period_start': ds.isoformat(),
            'period_end': de.isoformat(),
            'period_days': (de - ds).days + 1,
        }
    return _empty_window()


def parse_period_window_hangqingbiao_fallback(detail_url: str) -> dict:
    """行情表兜底：从 URL YYYYMM → 当月窗口（适用时间 PDF 解析失败时用）"""
    if not detail_url:
        return _empty_window()
    m = re.search(r'/(\d{4})(\d{2})/t\d{8}_\d+\.html', detail_url)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        ds = date(y, mo, 1)
        de = date(y, mo, _last_day(y, mo))
        return {
            'period_start': ds.isoformat(),
            'period_end': de.isoformat(),
            'period_days': (de - ds).days + 1,
        }
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

def parse_period_label(title: str, kind: str) -> str:
    """从 title 提取 period 业务期号

    行情资讯：'2026年第一期（1-2月份）...行情资讯' → '2026.第1期(行情资讯)'
    行情表：  '2026年全省第八期钢筋、水泥、...行情表' → '2026.第8期(行情表)'
    """
    if kind == 'zixun':
        m = re.search(r'(\d{4})\s*年\s*第?([一二三四五六七八九十\d]+)期', title)
        if m:
            y, n = m.group(1), _cn_to_int(m.group(2))
            return f'{y}.第{n}期(行情资讯)' if n else f'{y}.?(行情资讯)'
    elif kind == 'hangqingbiao':
        m = re.search(r'(\d{4})\s*年\s*全省\s*第?([一二三四五六七八九十\d]+)期', title)
        if m:
            y, n = m.group(1), _cn_to_int(m.group(2))
            return f'{y}.第{n}期(行情表)' if n else f'{y}.?(行情表)'
    return title[:30]


def extract_publish_date(detail_url: str) -> str:
    """从 detail_url 抽发布日期 tYYYYMMDD_xxx.html → YYYY-MM-DD"""
    m = re.search(r't(\d{4})(\d{2})(\d{2})_\d+\.html', detail_url)
    if m:
        return f'{m.group(1)}-{m.group(2)}-{m.group(3)}'
    return ''


# ─────────────────────────────────────────────────────────────
# HunanCollector - 湖南 SyncRunner 化主类
# ─────────────────────────────────────────────────────────────

class HunanCollector(SyncRunner):
    """湖南建设工程材料价格行情采集器（v0.8 SyncRunner 化）。

    工作单元形状：dict（含 period 业务期号、URL、PDF URL 占位等）
    """

    def __init__(
        self,
        cfg: dict,
        year: int,
        run_id: str,
        kinds: Optional[list[str]] = None,
    ):
        progress_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            '.hunan_sync_progress.json',
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
        self.kinds = kinds or ['zixun', 'hangqingbiao']
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
        """抓 14 页列表 → 过滤 year + journal_keywords → 计算 period 窗口 → 排除已 done

        注：LocalProgressStore.is_done 只查平铺 key，所以这里在返 list 前先
        加载本地 + ES 进度，手动过滤掉 status='ok'/'completed' 的 unit。
        """
        items = _legacy.fetch_all_periods(self.cfg)
        keywords = self.cfg.get('journal_keywords', [])
        # 过滤
        todo = []
        for it in items:
            if not any(kw in it['title'] for kw in keywords):
                continue
            if f'{self.year}年' not in it['title']:
                continue
            kind = _legacy._detect_period_kind(it['title'])
            if kind not in self.kinds:
                continue
            period = parse_period_label(it['title'], kind)
            unit = {
                'period': period,
                'period_kind': kind,
                'title': it['title'],
                'publish_date': extract_publish_date(it['detail_url']),
                'detail_url': it['detail_url'],
                'pdf_url': '',
                'minio_key': '',
                'period_start': '',
                'period_end': '',
                'period_days': 0,
            }
            # 行情资讯的 period 窗口可以从 title 直接算（写进 unit）
            if kind == 'zixun':
                w = parse_period_window_zixun(it['title'])
                unit['period_start'] = w['period_start']
                unit['period_end'] = w['period_end']
                unit['period_days'] = w['period_days']
            todo.append(unit)
        # 按期号排序（让 progress 输出稳定）
        todo.sort(key=lambda u: (u.get('publish_date',''), u['period']))

        # 过滤已 done（LocalProgressStore.is_done 只查平铺 key，progress 文件是嵌套
        # {"done": {detail_url: {...}}} 结构，故手动查进度）
        done_map = self.progress.load().get('done', {})
        before = len(todo)
        todo = [u for u in todo if (done_map.get(u['detail_url'], {}).get('status') not in ('ok', 'completed'))]
        skipped = before - len(todo)
        if skipped:
            print(f'  [progress] 跳过 {skipped} 个已 done 的工作单元（status=ok）')
        return todo

    def _process_one(self, unit: dict) -> tuple[int, str]:
        """处理单个工作单元：抓详情 → PDF → MinIO → 解析 → bulk_index

        Returns:
            (docs_count, status)，status ∈ {'completed', 'error', 'skipped'}。
        """
        kind = unit['period_kind']
        title = unit['title']

        # 1. 抓详情页抽 PDF URL
        try:
            pdf_title, pdf_url = _legacy.fetch_detail_pdf(self.cfg, unit['detail_url'])
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
                _legacy.download_file(pdf_url, local_pdf, timeout=600)
            except Exception as e:
                print(f"  ✗ 下载 PDF 失败: {e}")
                return 0, "error"

            # 3. 上传 MinIO（如果未上传）
            basename = _legacy.pdf_basename(pdf_url)
            minio_key = f"{self.cfg['minio']['prefix']}/{unit['period']}/{basename}"
            try:
                if not self._minio_exists(self.cfg['minio']['bucket'], minio_key):
                    _legacy.upload_to_minio(self.s3, self.cfg['minio']['bucket'], minio_key, local_pdf)
            except Exception as e:
                print(f"  ✗ 上传 MinIO 失败: {e}")
                return 0, "error"
            unit['minio_key'] = minio_key

            # 4. 解析 period 窗口
            if kind == 'hangqingbiao':
                w = parse_period_window_hangqingbiao_from_pdf(local_pdf)
                if not w['period_start']:  # 兜底用 URL YYYYMM
                    w = parse_period_window_hangqingbiao_fallback(unit['detail_url'])
                unit['period_start'] = w['period_start']
                unit['period_end'] = w['period_end']
                unit['period_days'] = w['period_days']

            # 5. PDF 解析 → 长表
            if kind == 'zixun':
                rows = _legacy.parse_zixun_pdf(local_pdf, unit['period'])
            elif kind == 'hangqingbiao':
                import pdfplumber
                with pdfplumber.open(local_pdf) as pdf:
                    rows = _legacy.parse_half_month_table(pdf.pages[0], unit['period'])
            else:
                rows = []

            if not rows:
                print(f"  [skipped] {unit['period']}：PDF 解析无数据")
                return 0, "skipped"

            # 6. 转 ES doc 列表（带 period_start/end/days）
            period_window = {
                'period_start': unit['period_start'],
                'period_end': unit['period_end'],
                'period_days': unit['period_days'],
            }
            docs = _new_docs_for_es(
                rows, unit['period'], period_window,
                minio_key, pdf_url, unit.get('publish_date', ''),
            )
            ok, err = _legacy.bulk_index(self.es, self.es_index, docs)
            if err:
                print(f"  ✗ bulk_index 失败: {ok} ok, {err} err")
                return ok, "error"
            return ok, "completed"

    def _on_unit_done(self, unit, docs_count: int, status: str, error: str = "") -> None:
        """完成后：写 ES progress + 本地进度 + 打印"""
        now = datetime.now().isoformat(timespec='seconds')
        # 本地进度
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
        print(f"  [{icon}] {unit['period']:30s} {win:40s}  docs={docs_count:5d}  ({status})")

    def _compute_unit_key(self, unit) -> str:
        """本地进度 key：unit['detail_url']

        注：LocalProgressStore.is_done 只查平铺 key，但本 collector 的 progress 文件用
        嵌套 {"done": {url: ...}} 结构。_list_work_units 已经预过滤 done，_on_unit_done
        用嵌套格式保存。这里 key 用 'hn:' 前缀 + url，避免与可能存在的平铺 key 冲突。
        """
        return f'hn:{unit["detail_url"]}'

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

def make_collector(cfg_path: str, year: int, run_id: str, kinds: Optional[list[str]] = None) -> HunanCollector:
    """从 config.yml 构造 HunanCollector。

    Args:
        cfg_path: config.yml 绝对路径
        year: 同步年份（如 2026）
        run_id: 本次运行标识
        kinds: 限定 kind（None=默认 ['zixun','hangqingbiao']）
    """
    cfg = _utils.load_config()
    return HunanCollector(
        cfg=cfg,
        year=year,
        run_id=run_id,
        kinds=kinds,
    )

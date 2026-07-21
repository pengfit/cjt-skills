"""sync_legacy.py - v3 旧路径的导入别名

新 sync.py 是 CLI 入口（4 行）。旧主流程和工具函数保留在 sync_v3_legacy.py。
本模块统一从 sync_v3_legacy 导出，供 ningxia_collector.py 复用：
    import sync_legacy as _legacy
    _legacy.fetch_all_periods(...)

v0.9 (2026-07-21)：fetch_all_periods / fetch_detail_pdf 改走浏览器版
  源站 jst.nx.gov.cn 启用 CT2-WAAP（知道创宇）拦截 HTTP requests（412 + 滑块挑战）。
  通过 ningxia_browser_fetch 用 openclaw browser 替代 requests，
  collector / preview 不用改——通过本模块 import 即可拿到浏览器版 fetch。
  PDF 解析 / 索引 / 进度等仍走原 sync_v3_legacy。
"""
from sync_v3_legacy import (
    # 列表 HTML 解析（仍由 v3 提供，浏览器版在 JS 里现抽，不再依赖 HTML 字符串）
    parse_list_page,
    pdf_basename,
    # PDF 解析
    parse_pdf,
    bulk_index,
    _doc_id,
    # 解析辅助
    _parse_price,
    _parse_material_table,
    _parse_quota_table,
    # 进度（v3 用嵌套结构）
    load_progress,
    save_progress,
    PROGRESS_FILE,
)
# v0.9 (2026-07-21) 网络抓取改走浏览器（绕开 CT2-WAAP）
from ningxia_browser_fetch import (
    fetch_all_periods,
    fetch_detail_pdf,
)

__all__ = [
    'parse_list_page', 'fetch_all_periods', 'fetch_detail_pdf', 'pdf_basename',
    'parse_pdf', 'bulk_index', '_doc_id',
    '_parse_price', '_parse_material_table', '_parse_quota_table',
    'load_progress', 'save_progress', 'PROGRESS_FILE',
]

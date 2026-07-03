"""sync_legacy.py - v3 旧路径的导入别名

新 sync.py 是 CLI 入口（4 行）。旧主流程和工具函数保留在 sync_v3_legacy.py。
本模块统一从 sync_v3_legacy 导出，供 ningxia_collector.py 复用：
    import sync_legacy as _legacy
    _legacy.fetch_all_periods(...)
"""
from sync_v3_legacy import (
    # 列表/详情页
    parse_list_page,
    fetch_all_periods,
    fetch_detail_pdf,
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

__all__ = [
    'parse_list_page', 'fetch_all_periods', 'fetch_detail_pdf', 'pdf_basename',
    'parse_pdf', 'bulk_index', '_doc_id',
    '_parse_price', '_parse_material_table', '_parse_quota_table',
    'load_progress', 'save_progress', 'PROGRESS_FILE',
]

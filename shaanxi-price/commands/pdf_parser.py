"""陕西省工程造价 PDF 解析器主入口。

设计：
- 按 city 维度分发到 `city_parsers.py` 的独立解析函数
- OCR 兑底（处理图像型 PDF）
- 公共入口：`parse_pdf_pages(pdf_path, city)`

注：
- 安康 PDF（2026.1-4期）是扫描图像型，OCR 跑通但解析器不识别 OCR 输出格式，
  sync 流程直接标记为 `skipped_image_pdf`，不进 parser。
- 各 city 的具体解析逻辑见 `city_parsers.py`。
"""
import time

import pypdf

from city_parsers import (
    parse_page, parse_page as _parse_page,  # 别名兼容
    MaterialRow,
    CITY_PARSERS,
)


# ─── OCR 兑底（处理图像型 PDF） ──────────────────────────────────────────────
_OCR_CACHE: dict = {}  # page_index -> text （避免重复 OCR）
_OCR_ENABLED = True   # 进程级开关：未安装 tesseract / poppler 时设为 False


def _ocr_disabled_check():
    """检查 OCR 依赖是否可用。不可用时返回 False。"""
    global _OCR_ENABLED
    if not _OCR_ENABLED:
        return False
    import shutil
    if not shutil.which('tesseract'):
        return False
    return True


def _ocr_page(pdf_path, page_index_0based, dpi=200, lang='chi_sim+eng'):
    """OCR 渲染并识别 PDF 的第 page_index_0based 页，返回文字。
    
    历史原因保留：安康部分期是扫描图像 PDF，pypdf 提取不到文本。
    实际 sync 流程不再依赖 OCR（直接 mark skipped_image_pdf），但保留能力备用。
    """
    cache_key = (pdf_path, page_index_0based, dpi, lang)
    if cache_key in _OCR_CACHE:
        return _OCR_CACHE[cache_key]
    try:
        from pdf2image import convert_from_path
        import pytesseract
    except Exception:
        return ''
    t0 = time.time()
    try:
        imgs = convert_from_path(pdf_path, dpi=dpi,
                                 first_page=page_index_0based + 1,
                                 last_page=page_index_0based + 1)
    except Exception as e:
        print(f'  [OCR] render fail p{page_index_0based+1}: {e}')
        return ''
    if not imgs:
        return ''
    img = imgs[0]
    best_text = ''
    best_chinese = 0
    for angle in (270, 0, 90, 180):
        try:
            rotated = img.rotate(angle, expand=True) if angle else img
            text = pytesseract.image_to_string(rotated, lang=lang, config='--psm 6')
            cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
            if cn > best_chinese:
                best_text = text
                best_chinese = cn
            if cn > 100:
                break
        except Exception:
            continue
    elapsed = time.time() - t0
    print(f'  [OCR] p{page_index_0based+1}: {elapsed:.1f}s, text {len(best_text)} chars, {best_chinese} CN')
    _OCR_CACHE[cache_key] = best_text
    return best_text


# ─── 主入口 ────────────────────────────────────────────────────────────────

def parse_pdf_pages(pdf_path, city):
    """解析整个 PDF，返回所有 (page_no, rows) 的列表。
    
    Args:
        pdf_path: PDF 文件路径
        city: 设区市名（如 '咸阳'、'汉中'）或 '陕西'（省本级）
    
    Returns:
        list of (page_no, page_type, rows) — page_type 保留供 sync 兼容（'parsed'）
    """
    reader = pypdf.PdfReader(pdf_path)
    # 打开 pdfplumber（部分 city 如商洛需要 Page 对象）
    plumber = None
    try:
        import pdfplumber
        plumber = pdfplumber.open(pdf_path)
        plumber_pages = list(plumber.pages)
    except Exception:
        plumber = None
        plumber_pages = []

    # 验证 city 有对应 parser
    if city not in CITY_PARSERS:
        print(f'  [parse_pdf_pages] unknown city: {city}（CITY_PARSERS 含: {list(CITY_PARSERS.keys())}）')
        return []

    results = []
    for pno, page in enumerate(reader.pages):
        text = page.extract_text() or ''
        # OCR 兑底（仅在 text 极少时启用，目前主要给 安康 备用）
        if len(text.strip()) < 50 and _ocr_disabled_check():
            text = _ocr_page(pdf_path, pno)

        if not text:
            continue

        page_obj = plumber_pages[pno] if pno < len(plumber_pages) else None
        try:
            rows = parse_page(text, city, page_obj)
        except Exception as e:
            results.append((pno + 1, f'error:{e}', []))
            continue
        if rows:
            results.append((pno + 1, 'parsed', rows))

    if plumber is not None:
        plumber.close()
    return results


# ─── CLI 调试入口 ──────────────────────────────────────────────────────────
if __name__ == '__main__':
    import sys
    if len(sys.argv) < 3:
        print('Usage: pdf_parser.py <pdf_path> <city>')
        print(f'  supported cities: {list(CITY_PARSERS.keys())}')
        sys.exit(1)
    path = sys.argv[1]
    city = sys.argv[2]
    results = parse_pdf_pages(path, city)
    total = 0
    for pno, ptype, rows in results:
        if rows:
            print(f'Page {pno} ({ptype}): {len(rows)} rows')
            for r in rows[:2]:
                print(f'  {r.code} | {r.breed[:20]:20} | {r.spec[:20]:20} | {r.unit:5} | county={r.county:6} | price={r.price} | tax={r.tax_price}')
            total += len(rows)
    print(f'\nTotal: {total} rows')

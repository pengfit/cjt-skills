"""新疆工程造价信息采集 - 列表抓取（AJAX API）+ 详情页解析 + xlsx 下载"""
import os
import re
import sys
import time

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import http_post, http_get, download_file, load_config, extract_period


def fetch_list(cfg, areaid, page=1, page_size=None):
    """调用 /Home/GetPoliciesListBy 抓一个地区一页的政策列表"""
    site = cfg['site']
    page_size = page_size or site.get('page_size', 50)
    url = site['base_url'].rstrip('/') + site['list_api']
    data = {
        'guid': site['detail_menu_id'],
        'areaid': str(areaid),
        'page': str(page),
        'pagesize': str(page_size),
        'title': '',
        'content': '',
        'rnd': f'{time.time():.6f}',
    }
    headers = {
        'Referer': f"{site['base_url']}/Home/Policies/C2A45B5E-FB3E-43C6-A77C-000000000456?tid={site['detail_menu_id']}&areaid={areaid}",
        'Origin': site['base_url'],
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    }
    return http_post(url, data, headers=headers, timeout=site.get('timeout_sec', 30))


def fetch_all_policies(cfg, areaid):
    """抓一个地区所有页（按 Total 自动翻页）"""
    site = cfg['site']
    page_size = site.get('page_size', 50)
    policies = []
    page = 1
    while True:
        try:
            obj = fetch_list(cfg, areaid, page=page, page_size=page_size)
        except Exception as e:
            raise RuntimeError(f'抓取 areaid={areaid} page={page} 失败: {e}')
        rows = obj.get('Rows', []) or []
        total = int(obj.get('Total', 0))
        policies.extend(rows)
        if not rows or len(policies) >= total:
            break
        page += 1
        time.sleep(0.3)
    return policies


def filter_target_year(policies, year):
    """按标题里出现的年月过滤，只保留目标年份"""
    out = []
    year_re = re.compile(rf'{year}\s*年\s*(\d{{1,2}})\s*月')
    for p in policies:
        title = p.get('Name', '') or ''
        if year_re.search(title):
            # 解析 period
            period, y = extract_period(title, year)
            if y == year:
                p['_period'] = period
                p['_year'] = y
                out.append(p)
    return out


def parse_detail_page(html):
    """解析详情页 → 提取 .xlsx 附件链接列表"""
    # 抓所有 LookFile(...) 路径
    paths = re.findall(r"LookFile\(\s*['\"]([^'\"]+)['\"]\s*\)", html)
    return paths


def pick_xlsx_files(paths):
    """从附件路径中过滤价格表 Excel 文件（.doc/.docx 是编制说明，跳过）

    支持 .xlsx 和 .xls 两种格式。
    """
    out = []
    for p in paths:
        # URL 解码后判断扩展名
        from urllib.parse import unquote
        decoded = unquote(p)
        low = decoded.lower()
        # 跳过 Office 临时文件（~$xxx.xlsx）和编制说明
        if '~$' in low.split('/')[-1]:
            continue
        if low.endswith(('.xlsx', '.xls')):
            out.append(p)
    return out


def release_date_iso(ms):
    """'/Date(1780406204000)/' → '2026-06-01'"""
    if not ms:
        return ''
    m = re.match(r'/Date\((-?\d+)\)/', ms.strip())
    if not m:
        return ''
    ts = int(m.group(1)) / 1000.0
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d')


# ─── CLI 调试入口 ─────────────────────────────────────────────────────────────
def main():
    import argparse
    import json as _json
    parser = argparse.ArgumentParser(description='新疆 - 抓取 + 解析详情页 + 下载 xlsx')
    parser.add_argument('--areaid', type=int, required=True, help='地区 areaid')
    parser.add_argument('--year', type=int, default=2026, help='目标年份')
    parser.add_argument('--download', action='store_true', help='下载 xlsx 到 ./downloads/<policy_id>/')
    args = parser.parse_args()

    cfg = load_config()
    print(f'[xinjiang] 抓取 areaid={args.areaid}, year={args.year}')
    policies = fetch_all_policies(cfg, args.areaid)
    print(f'  总条数: {len(policies)}')
    targets = filter_target_year(policies, args.year)
    print(f'  {args.year} 年: {len(targets)} 条')
    for p in targets[:10]:
        period = p.get('_period', '')
        date = release_date_iso(p.get('ReleaseDate', ''))
        print(f"    [{p['ID']}] {p['Name']} ({date}) period={period}")

    if args.download:
        site = cfg['site']
        base = site['base_url']
        save_root = os.path.join(os.path.dirname(SCRIPT_DIR), 'downloads', f'area_{args.areaid}')
        os.makedirs(save_root, exist_ok=True)
        for p in targets:
            detail_url = f"{base}{site['detail_path']}{p['ID']}"
            html = http_get(detail_url, timeout=site.get('timeout_sec', 30))
            paths = parse_detail_page(html)
            xlsx_paths = pick_xlsx_files(paths)
            print(f"  [{p['ID']}] 附件: xlsx={len(xlsx_paths)}, all={len(paths)}")
            sub = os.path.join(save_root, str(p['ID']))
            os.makedirs(sub, exist_ok=True)
            for i, path in enumerate(xlsx_paths):
                file_url = base + path
                from urllib.parse import unquote
                fname = unquote(os.path.basename(path))
                dest = os.path.join(sub, fname)
                if not os.path.exists(dest):
                    download_file(file_url, dest, timeout=120)
                    print(f'    ✓ {fname}')


if __name__ == '__main__':
    main()

"""预览命令 - 抓取页面数据并预览（不写入 ES）"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
warnings.filterwarnings('ignore')

from commands.utils import SiteSession, parse_page_date, parse_county, parse_table_rows, format_table, load_config, COUNTY_CODES


def main():
    import argparse
    parser = argparse.ArgumentParser(description='预览西安材料价格数据')
    parser.add_argument('--pages', type=int, default=1, help='预览页数（默认 1）')
    parser.add_argument('--county', type=str, default=None, help='只抓取指定区县')
    parser.add_argument('--config', type=str, default=None, help='配置文件路径')
    args = parser.parse_args()

    script_dir = __file__.rsplit('/', 1)[0]
    config_path = args.config or f"{script_dir}/../config.yml"
    config = load_config(config_path)

    counties = config['site']['counties']

    if args.county:
        if args.county not in counties:
            print(f"[!] 未知区县: {args.county}，可选: {', '.join(counties)}")
            sys.exit(1)
        counties = [args.county]

    session = SiteSession()
    page_count = 0
    total_rows = 0

    for county in counties:
        code = COUNTY_CODES.get(county, county)
        print(f"\n{'='*60}")
        print(f"  区县: {county} ({code})")
        print(f"{'='*60}")

        page = 1
        while page <= args.pages:
            html = session.fetch(county=county, page=page)
            if not html:
                print(f"  [!] 页面 {page} 抓取失败")
                break

            page_county = parse_county(html)
            update_date = parse_page_date(html)
            rows = parse_table_rows(html)

            print(f"\n  [页 {page}] {county}/{page}  区县={page_county}  更新={update_date}  数据={len(rows)}条")

            if not rows:
                break

            # 显示前 5 条
            headers = ['code', 'breed', 'spec', 'unit', 'price', 'tax_price']
            preview_rows = []
            for r in rows[:5]:
                preview_rows.append([
                    r['code'],
                    r['breed'][:20] + '...' if len(r['breed']) > 20 else r['breed'],
                    r['spec'][:15] + '...' if len(r['spec']) > 15 else r['spec'],
                    r['unit'],
                    str(r['price']) if r['price'] else '/',
                    str(r['tax_price']) if r['tax_price'] else '/',
                ])
            print(f"\n  {format_table(headers, preview_rows)}")
            if len(rows) > 5:
                print(f"  ... (还有 {len(rows) - 5} 条)")

            total_rows += len(rows)
            page += 1

        if page > args.pages:
            print(f"\n  [✓] 已预览 {args.pages} 页")

    print(f"\n{'='*60}")
    print(f"  预览完成: 共 {total_rows} 条记录")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()

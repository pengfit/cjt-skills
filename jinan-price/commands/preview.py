"""济南工程造价材料信息 - 预览"""
import sys, os, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
warnings.filterwarnings('ignore')

from commands.utils import JinAnSiteSession, load_config


def main():
    parser = argparse.ArgumentParser(description='预览济南材料价格数据')
    parser.add_argument('--pages', type=int, default=2, help='预览页数')
    parser.add_argument('--period-id', default='', help='指定 periodId')
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config = load_config(os.path.join(script_dir, 'config.yml'))
    data_type = config.get('site', {}).get('data_type', '2')
    size = config.get('sync', {}).get('size_per_page', 100)

    print("[i] 初始化 Session...")
    session = JinAnSiteSession()

    if args.period_id:
        period_id = args.period_id
        period_name = session._get_period_name(period_id)
    else:
        period_name, period_id = session.get_last_period()

    if not period_name:
        print("[!] 无法获取周期")
        return

    print(f"[i] 周期: {period_name}\n")

    # 获取分类目录
    all_cat_ids = session.get_all_catalogue_ids(data_type)
    print(f"[i] 共 {len(all_cat_ids)} 个分类\n")

    total_shown = 0
    for cat_id in all_cat_ids[:10]:
        # 获取分类名称
        tree = session.get_catalogue_tree(data_type)
        cat_name = ''
        for node in tree:
            if str(node.get('id', '')) == str(cat_id):
                cat_name = node.get('name', '')
                break

        print(f"[{cat_name or cat_id}]")
        for page_num in range(1, args.pages + 1):
            data = session.fetch(period_id, cat_id, page=page_num, size=size, data_type=data_type)
            if not data:
                break
            records = data.get('records', [])
            if not records:
                break
            for r in records:
                price = r.get('infoPrice', '?')
                unit = r.get('unit', '?')
                name = r.get('productName', '?')
                features = r.get('features', '') or ''
                print(f"  {name} {features} | {price}/{unit}")
                total_shown += 1
        print()

    print(f"[i] 共预览 {total_shown} 条记录")


if __name__ == '__main__':
    main()

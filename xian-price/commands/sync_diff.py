"""差量同步:仅抓 ES 缺数据的 (county, period) 组合

逻辑:
1. 对每个区县调用 Handler.ashx 拿所有可用周期
2. 对每个 (county, period) 组合:访问网站该月首页拿 total,与 ES 中 {county, month} count 对比
3. 差异 > 0 的加入 jobs
4. 调用 sync.py 跑这些 jobs(单次调用,带多个 --period)

用法:
    python3 commands/sync_diff.py [--period 2026-01,2026-02] [--counties 阎良区,...] [--dry-run]
"""
import sys, os, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from commands.utils import SiteSession, parse_total_records, list_all_years, load_config
import requests


ES_HOST_DEFAULT = 'http://localhost:59200'


def get_es_count(es_host, es_index, county, month):
    try:
        r = requests.post(
            f'{es_host}/{es_index}/_count',
            json={'query': {'bool': {'must': [
                {'term': {'county': county}},
                {'term': {'month': month}},
            ]}}},
            timeout=15, verify=False
        )
        return r.json().get('count', 0)
    except Exception:
        return 0


def get_site_total(county, period, gkbh, sess):
    html = sess.fetch(county, page=1, gkbh=gkbh)
    if not html:
        return 0
    return parse_total_records(html)


def main():
    parser = argparse.ArgumentParser(description='差量同步:仅抓缺数据的周期')
    parser.add_argument('--period', type=str, default=None, help='限定周期范围,逗号分隔')
    parser.add_argument('--counties', type=str, default=None, help='限定区县,逗号分隔')
    parser.add_argument('--dry-run', action='store_true', help='只检测,不抓取')
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = load_config(os.path.join(script_dir, 'config.yml'))
    es_host = cfg['es']['host']
    es_index = cfg['es']['index']
    all_counties = cfg['site']['counties']

    if args.counties:
        counties = [c.strip() for c in args.counties.split(',')]
    else:
        counties = all_counties

    wanted_periods = None
    if args.period:
        wanted_periods = set()
        for p in args.period.split(','):
            p = p.strip()
            if p:
                wanted_periods.add(p)

    print('[i] 差量检测...')
    sess = SiteSession(max_retries=2, timeout=15)
    missing = []  # [(county, period, gkbh, site_total, es_count, diff)]

    for county in counties:
        years = list_all_years(county, sess)
        for y in years:
            ps = sess.list_periods(county, y)
            for p in ps:
                period = p.get('period')
                if not period:
                    continue
                if wanted_periods and period not in wanted_periods:
                    continue
                gkbh = p.get('id', '')
                site_total = get_site_total(county, period, gkbh, sess)
                es_count = get_es_count(es_host, es_index, county, period)
                diff = site_total - es_count
                label = f"{county} {period}"
                if site_total == 0:
                    print(f'  [{label}] 源站抓取失败,跳过')
                    continue
                if diff > 0:
                    print(f'  [{label}] 网站 {site_total} > ES {es_count}  (+{diff})  ⚠')
                    missing.append((county, period, gkbh, site_total, es_count, diff))
                else:
                    print(f'  [{label}] ✓ {site_total} 条已齐')

    if not missing:
        print('\n[—] 无缺失')
        return

    print(f'\n[i] 缺失 {len(missing)} 个 (区县×周期)')
    for county, period, gkbh, st, ec, df in missing:
        print(f'  {county} {period}: 缺 {df} 条')

    if args.dry_run:
        print('\n[dry-run] 不触发 sync')
        return

    # 按区县聚合周期
    by_county = {}
    for county, period, *_ in missing:
        by_county.setdefault(county, []).append(period)

    print('\n[→] 启动 sync 跑缺失周期(后台)...')
    for county, periods in by_county.items():
        log_file = f'/tmp/xian-sync-diff-{county}.log'
        cmd = ['python3', 'commands/sync.py', '--force', '--no-spot-check',
               f'--counties={county}', f'--period={",".join(periods)}']
        ret = subprocess.Popen(
            cmd,
            cwd=script_dir,
            env={**os.environ},
            stdout=open(log_file, 'w'),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        print(f'  [{county}] PID {ret.pid}  周期:{",".join(periods)}  日志:{log_file}')

    print('\n[✓] sync_diff.py 完成,sync 继续后台运行')


if __name__ == '__main__':
    main()

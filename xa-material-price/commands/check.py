"""西安工程造价材料信息 - 增量检测与触发同步

按 区县×周期 粒度检测 ES 缺失数据，发现后触发 sync 补抓。
- 遍历 6 个区县
- 对每个区县遍历所有有数据的周期（Handler.ashx 拉取）
- 对每个 (county, month) 组合:site_total vs es_count 对比
- 差异 > 0 的加到 changed 列表,按周期触发 sync

例: 阎良区 2026-01 缺 50 条 → 触发 sync --period 2026-01 --counties 阎良区
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import requests
from commands.utils import (
    SiteSession, parse_page_date, parse_total_records,
    load_config, list_all_years, COUNTY_CODES
)

ES_HOST = 'http://localhost:59200'


def get_site_total_by_period(county: str, period: str, gkbh: str, sess: SiteSession) -> int:
    """访问网站某区县某月第 1 页,拿该月总记录数"""
    html = sess.fetch(county, page=1, gkbh=gkbh)
    if not html:
        return 0
    return parse_total_records(html)


def get_es_count_by_period(es_host: str, es_index: str, county: str, month: str) -> int:
    """ES 中 (county, month) 组合的记录数"""
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


def get_es_count_by_county(es_host: str, es_index: str, county: str) -> int:
    """ES 中该区县的总记录数(老用法,无 month 字段的老数据也算)"""
    try:
        r = requests.post(
            f'{es_host}/{es_index}/_count',
            json={'query': {'term': {'county': county}}},
            timeout=15, verify=False
        )
        return r.json().get('count', 0)
    except Exception:
        return 0


def main():
    parser = argparse.ArgumentParser(description='西安材料价格增量检测')
    parser.add_argument('--legacy', action='store_true',
                        help='用老逻辑:按区县总记录数对比（不区分周期）')
    parser.add_argument('--dry-run', action='store_true',
                        help='只检测,不触发 sync')
    parser.add_argument('--counties', type=str, default=None,
                        help='指定区县(逗号分隔),默认全部 6 个')
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg_path = os.path.join(script_dir, 'config.yml')
    config = load_config(cfg_path)
    es_host = config['es']['host']
    es_index = config['es']['index']
    counties = config['site']['counties']

    if args.counties:
        specified = [c.strip() for c in args.counties.split(',')]
        invalid = [c for c in specified if c not in counties]
        if invalid:
            print(f'[!] 未知区县: {", ".join(invalid)}')
            sys.exit(1)
        counties = specified

    print('[i] 增量检测开始...')
    if args.legacy:
        print('[i] 模式: legacy（按区县总记录数）')
    else:
        print('[i] 模式: 按区县×周期粒度')

    sess = SiteSession(max_retries=3, timeout=30)
    changed: list = []  # [{'county', 'period', 'gkbh', 'site_total', 'es_count', 'diff'}]

    if args.legacy:
        # ── 老逻辑:按区县总记录数对比 ──
        for county in counties:
            html = sess.fetch(county, page=1)
            if not html:
                print(f'  [{county}] 获取失败,跳过')
                continue

            site_total = parse_total_records(html)
            site_date = parse_page_date(html)
            es_count = get_es_count_by_county(es_host, es_index, county)

            if site_total == 0:
                continue

            diff = site_total - es_count
            if diff > 0:
                print(f'  [{county}] 网站 {site_total} > ES {es_count}  (+{diff}) | 更新:{site_date}')
                changed.append({'county': county, 'period': '', 'gkbh': '', 'site_total': site_total, 'es_count': es_count, 'diff': diff, 'site_date': site_date})
            else:
                print(f'  [{county}] 一致 {site_total} | 更新:{site_date}')
    else:
        # ── 新逻辑:按 区县×周期 粒度 ──
        # 先按区县分组所有 (period, gkbh)
        all_jobs: dict = {}  # county -> [{period, gkbh, year}]
        years_per_county: dict = {}
        for county in counties:
            ys = list_all_years(county, sess)
            years_per_county[county] = ys
            jobs = []
            for y in ys:
                ps = sess.list_periods(county, y)
                for p in ps:
                    if p.get('period'):
                        jobs.append({'period': p['period'], 'gkbh': p.get('id', ''), 'year': y})
            all_jobs[county] = sorted(jobs, key=lambda x: x['period'])

        for county in counties:
            jobs = all_jobs.get(county, [])
            if not jobs:
                print(f'  [{county}] 源站无数据')
                continue
            print(f'  [{county}] 共 {len(jobs)} 个周期待检测')
            for job in jobs:
                site_total = get_site_total_by_period(county, job['period'], job['gkbh'], sess)
                es_count = get_es_count_by_period(es_host, es_index, county, job['period'])
                if site_total == 0:
                    print(f'    [{county} {job["period"]}] 源站抓取失败,跳过')
                    continue
                diff = site_total - es_count
                if diff > 0:
                    print(f'    [{county} {job["period"]}] 网站 {site_total} > ES {es_count}  (+{diff})  ⚠ 待补')
                    changed.append({
                        'county': county, 'period': job['period'], 'gkbh': job['gkbh'],
                        'site_total': site_total, 'es_count': es_count, 'diff': diff,
                        'site_date': '',
                    })
                else:
                    print(f'    [{county} {job["period"]}] ✓ {site_total} 条已齐')

    if not changed:
        print('\n[—] 无新增/缺失记录')
        return

    # ── 按 (county, period) 分组,生成 sync 命令 ──
    print(f'\n[i] 发现 {len(changed)} 个 (区县×周期) 缺失:')
    for c in changed:
        label = f"{c['county']} {c['period']}".strip() if c['period'] else c['county']
        print(f'  {label}: 缺 {c["diff"]} 条')

    if args.dry_run:
        print('\n[dry-run] 不触发 sync,直接退出')
        return

    # 按区县聚合周期列表
    by_county: dict = {}
    for c in changed:
        by_county.setdefault(c['county'], []).append(c['period'])

    print('\n[→] 触发增量同步（按区县聚合,后台运行）...')
    import subprocess
    for county, periods in by_county.items():
        period_arg = ','.join(periods)
        log_file = f'/tmp/xian-sync-{county}.log'
        ret = subprocess.Popen(
            ['python3', 'commands/sync.py', '--force', '--no-spot-check',
             f'--counties={county}', f'--period={period_arg}'],
            cwd=script_dir,
            env={**os.environ},
            stdout=open(log_file, 'w'),
            stderr=subprocess.STDOUT,
            start_new_session=True
        )
        print(f'  [{county}] PID {ret.pid}  周期:{period_arg}  日志:{log_file}')

    print('\n[✓] check.py 完成,sync.py 继续在后台运行')


if __name__ == '__main__':
    main()

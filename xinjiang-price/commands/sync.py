"""新疆工程造价信息采集 - 主同步流程

按 area 遍历（16 个地区）→ 抓政策列表 → 按年份过滤 → 抓详情页 → 下载 xlsx → 解析 → 写入 ES
"""
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime
from urllib.parse import unquote

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import (
    load_config, get_es_client, get_s3_client, ensure_bucket,
    ensure_ods_index, ensure_progress_index, http_get, download_file,
    upload_to_minio, extract_period, area_label,
)
from fetch import (
    fetch_all_policies, filter_target_year, parse_detail_page,
    pick_xlsx_files, release_date_iso,
)
from parse import parse_xlsx, split_breed_spec


PROGRESS_FILE = os.path.join(os.path.dirname(SCRIPT_DIR), '.xinjiang_sync_progress.json')


def load_progress():
    if not os.path.exists(PROGRESS_FILE):
        return {'done': {}, 'areas': {}}
    with open(PROGRESS_FILE) as f:
        return json.load(f)


def save_progress(prog):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(prog, f, ensure_ascii=False, indent=2)


def _doc_id(areaid, period, sheet_name, breed, spec, unit):
    raw = f'{areaid}|{period}|{sheet_name}|{breed}|{spec}|{unit}'
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


def bulk_index(es, index, docs):
    if not docs:
        return 0, 0
    body = ''
    for d in docs:
        _id = _doc_id(d['_areaid'], d['_period'], d['_sheet'], d['breed'], d['spec'], d['unit'])
        body += json.dumps({'index': {'_index': index, '_id': _id}}, ensure_ascii=False) + '\n'
        body += json.dumps(d, ensure_ascii=False) + '\n'
    resp = es.bulk(body=body, refresh=False)
    if resp.get('errors'):
        errors = sum(1 for it in resp['items'] if 'error' in it.get('index', {}))
        return len(docs) - errors, errors
    return len(docs), 0


def sync_one_policy(es, s3, cfg, area, policy, year, minio_prefix, dry_run=False):
    """处理单条政策：下载 xlsx → 解析 → 写入 ES → 写进度"""
    site = cfg['site']
    base = site['base_url'].rstrip('/')

    title = policy.get('Name', '')
    policy_id = str(policy.get('ID', ''))
    detail_url = f"{base}{site['detail_path']}{policy_id}"
    period = policy.get('_period', '')

    start = time.time()
    result = {
        'areaid': area['areaid'],
        'area_name': area['name'],
        'period': period,
        'policy_id': policy_id,
        'policy_title': title,
        'release_date': release_date_iso(policy.get('ReleaseDate', '')),
        'detail_url': detail_url,
        'status': 'failed',
        'docs_written': 0,
        'duration_sec': 0,
    }

    try:
        # 1. 抓详情页 → 找 xlsx
        html = http_get(detail_url, timeout=site.get('timeout_sec', 30))
        paths = parse_detail_page(html)
        xlsx_paths = pick_xlsx_files(paths)
        if not xlsx_paths:
            raise ValueError(f'详情页无 xlsx 附件（paths={len(paths)}）')

        result['file_url'] = ','.join(base + p for p in xlsx_paths)
        print(f'  [{policy_id}] xlsx files: {len(xlsx_paths)}')

        total_docs = 0
        total_err = 0
        for xpath in xlsx_paths:
            file_url = base + xpath
            fname = unquote(os.path.basename(xpath))
            with tempfile.TemporaryDirectory() as tmpdir:
                local = os.path.join(tmpdir, fname)
                download_file(file_url, local, timeout=120)

                # 2. 上传 MinIO
                minio_key = f"{minio_prefix}/{area['areaid']}/{policy_id}/{fname}"
                if not dry_run:
                    try:
                        upload_to_minio(s3, cfg['minio']['bucket'], minio_key, local,
                                        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                    except Exception as e:
                        print(f'    [minio] 上传失败（不影响 ES 写入）: {e}')

                # 3. 解析
                rows = parse_xlsx(local, area['name'])
                if not rows:
                    print(f'    [parse] 0 行 ({fname})，跳过')
                    continue

                # 4. 构造 ES 文档
                now = datetime.now().isoformat(timespec='seconds')
                docs = []
                for r in rows:
                    # 拆分 breed 和 spec
                    breed_clean, spec_extracted = split_breed_spec(r['breed'])
                    # 优先使用原 spec 字段（如已拆分）否则用拆分结果
                    final_spec = r['spec'] if r['spec'] else spec_extracted
                    doc = {
                        '_areaid': str(area['areaid']),
                        '_period': period,
                        '_sheet': r['sheet_name'],
                        'breed': r['breed'],
                        'breed_clean': breed_clean,
                        'spec': final_spec,
                        'unit': r['unit'],
                        'price': round(r['price'], 2) if r['price'] is not None else None,
                        'tax_price': round(r['tax_price'], 2) if r['tax_price'] is not None else None,
                        'category': r['category'],
                        'period': period,
                        'province': '新疆',
                        'city': area['city'],
                        'county': r['sheet_name'],
                        'area_name': area['name'],
                        'update_date': result['release_date'],
                        'create_time': now,
                        'source_file': minio_key,
                        'source_url': file_url,
                        'source_id': policy_id,
                        'sheet_name': r['sheet_name'],
                    }
                    docs.append(doc)

                # 5. 入库
                if dry_run:
                    ok, err = len(docs), 0
                    print(f'    [dry-run] {fname}: {len(docs)} 条')
                else:
                    ok, err = bulk_index(es, cfg['es']['ods_index'], docs)
                    print(f'    {fname}: ok={ok}, err={err}')

                total_docs += ok
                total_err += err

        result['docs_written'] = total_docs
        result['status'] = 'ok' if total_err == 0 else 'partial'
        result['minio_key'] = minio_prefix + f"/{area['areaid']}/{policy_id}/"
        result['duration_sec'] = round(time.time() - start, 1)

    except Exception as e:
        result['status'] = 'failed'
        result['error'] = str(e)[:300]
        result['duration_sec'] = round(time.time() - start, 1)
        print(f'  ✗ [{policy_id}] {e}')

    return result


def sync_one_area(es, s3, cfg, area, year, progress, minio_prefix, dry_run=False,
                  only_policy_ids=None, skip_existing=True):
    """处理单个 area 下的所有目标年政策"""
    areaid = area['areaid']
    print(f"\n{'='*60}\n[area {areaid}] {area_label(area)}\n{'='*60}")

    if skip_existing:
        # 检查 area 是否已完成（按 progress['areas'][areaid]）
        area_state = progress['areas'].get(str(areaid), {})
        if area_state.get('status') == 'ok' and area_state.get('last_year') == year:
            print(f'  已完成（{area_state.get("docs_written", 0)} 条），跳过')
            return {'areaid': areaid, 'skipped': True}

    print(f'  抓取列表...')
    policies = fetch_all_policies(cfg, areaid)
    print(f'  总条数: {len(policies)}')

    targets = filter_target_year(policies, year)
    print(f'  {year} 年: {len(targets)} 条')

    if only_policy_ids:
        targets = [p for p in targets if str(p['ID']) in set(map(str, only_policy_ids))]

    if not targets:
        print('  无目标')
        progress['areas'][str(areaid)] = {'status': 'ok', 'last_year': year, 'docs_written': 0}
        save_progress(progress)
        return {'areaid': areaid, 'total': 0, 'docs_written': 0}

    total_written = 0
    completed = 0
    run_id = f"xj_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{areaid}"
    last_updated = datetime.now().isoformat(timespec='seconds')
    for idx, p in enumerate(targets, 1):
        if skip_existing:
            key = f"{areaid}/{p['ID']}"
            done = progress['done'].get(key, {})
            if done.get('status') == 'ok':
                print(f'  [{idx}/{len(targets)}] 跳过已完成: {p["Name"]}')
                total_written += done.get('docs_written', 0)
                completed += 1
                continue

        print(f'\n  [{idx}/{len(targets)}] {p["Name"]}')
        res = sync_one_policy(es, s3, cfg, area, p, year, minio_prefix, dry_run=dry_run)
        total_written += res.get('docs_written', 0)

        key = f"{areaid}/{p['ID']}"
        progress['done'][key] = res
        save_progress(progress)

        # 写 ES 进度（policy 粒度，供溯源查询）
        if not dry_run:
            try:
                es.index(index=cfg['es']['progress_index'], body=res)
            except Exception as e:
                print(f'  [progress] ES 写入失败: {e}')

        if res.get('status') in ('ok', 'partial'):
            completed += 1

    area_state = {
        'status': 'ok',
        'last_year': year,
        'docs_written': total_written,
        'completed_count': completed,
        'total_count': len(targets),
        'updated_at': datetime.now().isoformat(timespec='seconds'),
    }
    progress['areas'][str(areaid)] = area_state
    save_progress(progress)

    # 写一条 area 级别的汇总进度（供 dashboard 的 county_details 用）
    # county_field 用 area_name（与 dashboard registry 推断一致）
    if not dry_run and targets:
        try:
            area_summary = {
                'run_id': run_id,
                'status': 'completed',  # dashboard 期望 completed
                'area': area['name'],
                'current_county': area['name'],
                'areaid': str(areaid),
                'period': f'{year}',
                'docs_written': total_written,
                'doc_count': total_written,
                'percent': 100.0,
                'duration_sec': round(sum(progress['done'].get(f"{areaid}/{p['ID']}", {}).get('duration_sec', 0) for p in targets), 1),
                'last_updated': last_updated,
                'update_date': last_updated[:10],
                'error': '',
            }
            es.index(index=cfg['es']['progress_index'], id=f'area_{areaid}_summary', body=area_summary)
            print(f'  [progress] area summary 写入: {area["name"]} ({total_written} 条)')
        except Exception as e:
            print(f'  [progress] area summary 写入失败: {e}')

    return {'areaid': areaid, 'total': len(targets), 'completed': completed, 'docs_written': total_written}


def main():
    parser = argparse.ArgumentParser(description='新疆工程造价信息采集 - 主流程')
    parser.add_argument('--year', type=int, default=2026, help='目标年份')
    parser.add_argument('--areaid', type=int, default=0, help='只同步指定 areaid（0=全部）')
    parser.add_argument('--reset', action='store_true', help='重置进度')
    parser.add_argument('--dry-run', action='store_true', help='只下载 + 解析，不入库')
    parser.add_argument('--no-skip', action='store_true', help='不跳过已完成的条目')
    args = parser.parse_args()

    cfg = load_config()
    es = get_es_client(cfg['es']['host'])
    s3 = get_s3_client(cfg)
    ensure_bucket(s3, cfg['minio']['bucket'])
    if not args.dry_run:
        ensure_ods_index(es, cfg['es']['ods_index'])
        ensure_progress_index(es, cfg['es']['progress_index'])

    progress = {'done': {}, 'areas': {}} if args.reset else load_progress()
    if args.reset:
        save_progress(progress)

    print(f'[xinjiang] ES: {cfg["es"]["host"]}')
    print(f'[xinjiang] MinIO: {cfg["minio"]["endpoint"]} / {cfg["minio"]["bucket"]}')
    print(f'[xinjiang] 目标年份: {args.year}')
    print(f'[xinjiang] 模式: {"DRY-RUN" if args.dry_run else "实际写入"}')

    areas = cfg['areas']
    if args.areaid:
        areas = [a for a in areas if a['areaid'] == args.areaid]
        if not areas:
            print(f'无效 areaid: {args.areaid}')
            return

    minio_prefix = cfg['minio']['prefix']
    grand_total = 0
    for area in areas:
        res = sync_one_area(es, s3, cfg, area, args.year, progress, minio_prefix,
                            dry_run=args.dry_run, skip_existing=not args.no_skip)
        grand_total += res.get('docs_written', 0)

    print(f'\n[xinjiang] 全部完成: total_written={grand_total}')


if __name__ == '__main__':
    main()

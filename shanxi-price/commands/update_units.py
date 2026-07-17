"""山西数据后处理: unit 归一 + 空 unit 补全 (增量安全版)

适用场景:
  1. 已入库数据有 OCR 噪声 (m / m? / 100m 等) 需归一
  2. 空 unit 需用 _UNIT_INFERENCE 兜底补齐
  3. 增量后再跑一次, 确保历史数据也一致

工作流 (都用 ES _update_by_query, 干跑可 --dry-run):
  - step 1: m → m³ (1349 条左右)
  - step 2: m? → m³ (105 条)
  - step 3: 空 unit + 可推断 breed → 补全 (3761 条左右, 实际能补上 70-80%)
  - step 4: 其他噪声 → 清空 (等下次 OCR 重处理)

用法:
  python3 commands/update_units.py             # 实际跑
  python3 commands/update_units.py --dry-run   # 预览
  python3 commands/update_units.py --step 1    # 只跑第 1 步
"""
import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import load_config, get_es_client
from sync import _clean_unit, _infer_unit


def update_by_query(es, index: str, query: dict, script: str, dry_run: bool = False) -> int:
    """update_by_query 包装."""
    body = {
        'query': query,
        'script': {
            'source': script,
            'lang': 'painless',
        },
    }
    if dry_run:
        # 计数预览
        cnt = es.count(index=index, body={'query': query})
        return cnt['count']
    res = es.update_by_query(
        index=index,
        body=body,
        refresh=True,
        conflicts='proceed',
        wait_for_completion=True,
    )
    return res.get('updated', 0)


def main():
    parser = argparse.ArgumentParser(description='山西 ODS unit 后处理 (归一 + 补空)')
    parser.add_argument('--dry-run', action='store_true', help='只统计, 不写')
    parser.add_argument('--step', type=int, default=0, help='只跑指定 step (1/2/3/4); 0=全跑')
    parser.add_argument('--batch-size', type=int, default=500, help='update_by_query batch_size')
    args = parser.parse_args()

    cfg = load_config()
    es = get_es_client(cfg['es']['host'])
    index = cfg['es']['ods_index']

    if not es.indices.exists(index=index):
        print(f'[update_units] 索引不存在: {index}')
        return

    total_updated = 0
    steps = []

    # step 1: m → m³
    if args.step in (0, 1):
        s = (
            "if (ctx._source.unit == 'm') { "
            "  ctx._source.unit = 'm³'; "
            "}"
        )
        n = update_by_query(es, index, {'term': {'unit': 'm'}}, s, args.dry_run)
        steps.append(('1. m → m³', n))
        total_updated += n

    # step 2: m? → m³
    if args.step in (0, 2):
        s = (
            "if (ctx._source.unit == 'm?') { "
            "  ctx._source.unit = 'm³'; "
            "}"
        )
        n = update_by_query(es, index, {'term': {'unit': 'm?'}}, s, args.dry_run)
        steps.append(('2. m? → m³', n))
        total_updated += n

    # step 3: 空 unit → 推断补齐
    # 用 scroll + bulk, 因为需要 Python 端推断 (painless 写 30+ 规则太啰嗦)
    if args.step in (0, 3):
        n = _fill_empty_units(es, index, args.dry_run)
        steps.append(('3. 空 unit → 推断补齐', n))
        total_updated += n

    # step 4: 其他 OCR 噪声 (100m / 100ms / 100ml / 之副) → 清空
    if args.step in (0, 4):
        s = (
            "if (['100m','100ms','100ml','之副','之剖'].contains(ctx._source.unit)) { "
            "  ctx._source.unit = ''; "
            "}"
        )
        # 用 terms 而不是 term 因为多值
        n = update_by_query(es, index, {'terms': {'unit': ['100m', '100ms', '100ml', '之副', '之剖']}}, s, args.dry_run)
        steps.append(('4. 噪声 unit → 清空', n))
        total_updated += n

    # 报告
    print(f'\n[update_units] {("预览" if args.dry_run else "完成")}, 共影响 {total_updated} 条:')
    for label, n in steps:
        print(f'  {label}: {n} 条')


def _fill_empty_units(es, index: str, dry_run: bool = False) -> int:
    """空 unit + 可推断 breed → 补全. 用 scroll + bulk."""
    from elasticsearch.helpers import scan, bulk

    cnt_before = es.count(index=index, body={'query': {'term': {'unit': ''}}})['count']
    print(f'[step 3] 空 unit 当前 {cnt_before} 条, 推断补齐中...')

    if dry_run:
        return cnt_before  # preview 阶段

    actions = []
    updated = 0
    for hit in scan(es, index=index, query={'query': {'term': {'unit': ''}}, '_source': ['breed']}, size=500):
        src = hit['_source']
        breed = src.get('breed', '')
        inferred = _infer_unit(breed)
        if inferred:
            actions.append({
                '_op_type': 'update',
                '_index': index,
                '_id': hit['_id'],
                'doc': {'unit': inferred},
            })
        # 批量提交
        if len(actions) >= 500:
            _, errs = bulk(es, actions, raise_on_error=False, refresh=False)
            updated += len(actions) - (len(errs) if isinstance(errs, list) else 0)
            actions = []

    if actions:
        _, errs = bulk(es, actions, raise_on_error=False, refresh=False)
        updated += len(actions) - (len(errs) if isinstance(errs, list) else 0)

    # refresh 让下次查询看得到
    es.indices.refresh(index=index)
    return updated


if __name__ == '__main__':
    main()
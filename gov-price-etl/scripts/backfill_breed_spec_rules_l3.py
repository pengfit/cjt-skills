"""回填 breed_spec_rules.l3：按 breed 聚合 DWD 的 category_l3，写回 db。
适用：之前修复前写入的 141 条规则，l3 全空。"""
import sys
import sqlite3
import requests
from collections import Counter

DB_PATH = '/Users/pengfit/.openclaw/workspace/cjt/skills/data/breed_spec_rules.db'
ES = 'http://localhost:59200'


def fetch_dwd_l3_by_breed(breed_value: str, size: int = 200) -> Counter:
    """对单个 breed，从 DWD 拉所有文档，统计 category_l3 桶数。"""
    body = {
        "size": size,
        "_source": ["category_l3"],
        "query": {"term": {"breed.keyword": breed_value}},
    }
    r = requests.post(f'{ES}/dwd_weihai_price/_search', json=body, timeout=10)
    if r.status_code != 200:
        return Counter()
    hits = r.json()["hits"]["hits"]
    c = Counter()
    for h in hits:
        l3 = h["_source"].get("category_l3", "")
        if l3:
            c[l3] += 1
    return c


def main():
    conn = sqlite3.connect(DB_PATH)
    # 1. 清掉之前直接 vs.insert 写的 3 条测试样本
    cur = conn.execute(
        "DELETE FROM breed_spec_rules WHERE attr IN ('pressure_dn', 'grade_strength', 'diameter_test')"
    )
    print(f"[清理] 测试样本删除 {cur.rowcount} 条")
    conn.commit()

    # 2. 找所有 l3 为空的 rule，按 breed 分组
    rows = conn.execute(
        "SELECT DISTINCT breed FROM breed_spec_rules WHERE (l3 IS NULL OR l3='') AND breed != ''"
    ).fetchall()
    breeds = [r[0] for r in rows]
    print(f"[回填] 需要回填的 breed 数: {len(breeds)}")

    updated = 0
    skipped_multi = 0
    skipped_missing = 0
    for breed in breeds:
        c = fetch_dwd_l3_by_breed(breed)
        if not c:
            skipped_missing += 1
            print(f"  [skip] breed={breed!r}: DWD 无 category_l3 记录")
            continue
        # 单 breed 通常对应 1 个 l3；但同 breed 可能跨多 l3（如钢筋多类型）
        # 策略：l3 与该 breed 在 DWD 文档数最多者；若有冲突，记录但仍写
        most_common_l3, _count = c.most_common(1)[0]
        # 检查是否有多个 l3（避免给钢筋都打一个错的 l3）
        if len(c) > 1:
            skipped_multi += 1
            print(f"  [warn] breed={breed!r}: DWD 跨多个 l3 {dict(c)}, "
                  f"用最高频 {most_common_l3}")
        cur = conn.execute(
            "UPDATE breed_spec_rules SET l3=? WHERE breed=? AND (l3 IS NULL OR l3='')",
            (most_common_l3, breed),
        )
        updated += cur.rowcount

    conn.commit()

    # 3. 校验
    total = conn.execute("SELECT COUNT(*) FROM breed_spec_rules").fetchone()[0]
    with_l3 = conn.execute(
        "SELECT COUNT(*) FROM breed_spec_rules WHERE l3 IS NOT NULL AND l3 != ''"
    ).fetchone()[0]
    print(f"\n[回填完成]")
    print(f"  updated      : {updated}")
    print(f"  multi-l3     : {skipped_multi}")
    print(f"  no DWD match : {skipped_missing}")
    print(f"\n[db 现状]")
    print(f"  total        : {total}")
    print(f"  with l3      : {with_l3}  ({with_l3*100//total if total else 0}%)")
    print(f"  empty l3     : {total - with_l3}")

    # 4. l3 分布前 10
    print(f"\n[l3 分布 Top 10]")
    rows = conn.execute(
        "SELECT l3, COUNT(*) AS n FROM breed_spec_rules WHERE l3 != '' GROUP BY l3 ORDER BY 2 DESC LIMIT 10"
    ).fetchall()
    for r in rows:
        print(f"  {r[0]:12s}  {r[1]}")

    conn.close()


if __name__ == "__main__":
    main()
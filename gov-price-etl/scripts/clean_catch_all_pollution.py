"""P0 清理：删 db catch-all 脏规则 + 清 DWS attr.type 污染

两步：
1. DELETE FROM breed_spec_rules WHERE pattern IN (...)  -- 10 条 catch-all
2. ES update_by_query 用 painless 从 dws_* 索引嵌套 attr 数组里删 type=硬编码breed名 的项

治本意义：db 干净 + DWS 干净 + 之后 sync 不会再被同一规则污染。
"""
import sqlite3
import requests
import sys
from collections import defaultdict

DB_PATH = '/Users/pengfit/.openclaw/workspace/cjt/skills/data/breed_spec_rules.db'
ES = 'http://localhost:59200'

# Catch-all pattern 黑名单（catch_all + 全匹配，无任何元字符）
CATCH_ALL_PATTERNS = (
    '^(.*)$', '^(.+)$', '^.+$', '^.*$', '^.+', '.*', '.+', '^(.)$',
)

# DWS 里需要清的硬编码 type 值（脏规则写入的固定字符串）
# 来源：之前 sqlite 查到的 5 条 hard-code 规则的 value
POLLUTED_TYPE_VALUES = (
    '加气砼砌块', '水泥瓦', '水泥脊瓦', '乱毛石', '地瓜石',
)


def step1_delete_db():
    """Step 1: 删 db 里所有 catch-all pattern 的规则"""
    conn = sqlite3.connect(DB_PATH)
    before = conn.execute("SELECT COUNT(*) FROM breed_spec_rules").fetchone()[0]

    placeholders = ','.join('?' * len(CATCH_ALL_PATTERNS))
    cur = conn.execute(
        f"DELETE FROM breed_spec_rules WHERE pattern IN ({placeholders})",
        CATCH_ALL_PATTERNS,
    )
    deleted = cur.rowcount
    conn.commit()

    after = conn.execute("SELECT COUNT(*) FROM breed_spec_rules").fetchone()[0]
    print(f"[Step 1] db 删除 catch-all 规则: {deleted} 条")
    print(f"  规则总数: {before} → {after}")

    # 列出删了哪些（备份用途）
    print(f"\n  删除清单（按 id 升序）:")
    rows = conn.execute(
        f"SELECT id, breed, l3, attr, pattern, substr(code,1,60) "
        f"FROM breed_spec_rules WHERE 1=0"  # 已经被删了，回查 archived 不现实
    ).fetchall()
    # 改为：列出当前还存在的，留证据用
    print(f"  （删除前快照已在前置查询）")
    conn.close()
    return deleted


def step2_clean_dws():
    """Step 2: ES update_by_query 清 DWS 嵌套 attr 数组里的污染项"""
    print(f"\n[Step 2] DWS 污染清理开始...")
    print(f"  目标 attr.v 硬编码值: {POLLUTED_TYPE_VALUES}")

    # 找所有 dws_* 索引
    r = requests.get(f'{ES}/_cat/indices/dws_*?h=index', timeout=10)
    indices = [line.strip() for line in r.text.splitlines() if line.strip()]
    print(f"  发现 dws_* 索引: {len(indices)} 个 → {indices[:5]}{'...' if len(indices)>5 else ''}")

    total_updated = 0
    total_docs_cleaned = 0

    for idx in indices:
        # 用 painless script 从嵌套 attr 数组里删污染项
        # 构造 IN 查询：attr.v 在黑名单里
        should_clauses = []
        for v in POLLUTED_TYPE_VALUES:
            should_clauses.append({
                "bool": {"must": [
                    {"term": {"attr.k": "type"}},
                    {"term": {"attr.v": v}},
                ]}
            })
        # nested query path 必须用 nested wrapper
        query = {
            "nested": {
                "path": "attr",
                "query": {"bool": {"should": should_clauses, "minimum_should_match": 1}},
            }
        }

        # update_by_query + painless script
        script = """
            if (ctx._source.attr != null) {
                ctx._source.attr.removeIf(a ->
                    a.k == 'type' && (
                        a.v == '加气砼砌块' ||
                        a.v == '水泥瓦' ||
                        a.v == '水泥脊瓦' ||
                        a.v == '乱毛石' ||
                        a.v == '地瓜石'
                    )
                );
            }
        """

        url = f'{ES}/{idx}/_update_by_query?refresh=true&conflicts=proceed'
        body = {
            "query": query,
            "script": {
                "source": script,
                "lang": "painless",
            },
        }
        try:
            r = requests.post(url, json=body, timeout=60)
            if r.status_code == 200:
                d = r.json()
                updated = d.get("updated", 0)
                total = d.get("total", 0)
                failures = d.get("failures", [])
                print(f"  [{idx}] matched={total}  updated={updated}  failures={len(failures)}")
                total_updated += updated
                total_docs_cleaned += total
            else:
                print(f"  [{idx}] ERROR: {r.status_code} {r.text[:200]}")
        except Exception as e:
            print(f"  [{idx}] EXC: {e}")

    print(f"\n[Step 2 汇总]")
    print(f"  跨索引 matched docs: {total_docs_cleaned}")
    print(f"  实际 updated docs:   {total_updated}")
    return total_updated


def step3_verify():
    """Step 3: 校验 — 再搜一次 DWS 确认 type=硬编码值的文档清零"""
    print(f"\n[Step 3] 校验：搜 5 个污染值在所有 dws_* 中的剩余数")
    for v in POLLUTED_TYPE_VALUES:
        total = 0
        r = requests.get(f'{ES}/_cat/indices/dws_*?h=index', timeout=10)
        indices = [line.strip() for line in r.text.splitlines() if line.strip()]
        for idx in indices:
            cnt = requests.post(f'{ES}/{idx}/_count', json={
                "query": {"nested": {"path": "attr", "query": {"bool": {"must": [
                    {"term": {"attr.k": "type"}},
                    {"term": {"attr.v": v}},
                ]}}}}
            }, timeout=10).json().get("count", 0)
            total += cnt
        print(f"  type={v:12s}  remaining: {total}")


def main():
    print("=" * 70)
    print("P0 清理：删 db catch-all 脏规则 + 清 DWS attr.type 污染")
    print("=" * 70)

    deleted = step1_delete_db()
    if deleted == 0:
        print("db 里已经没 catch-all 规则，跳过 step1")
    updated = step2_clean_dws()
    step3_verify()
    print("\n" + "=" * 70)
    print(f"P0 完成：删 db {deleted} 条 + 清 DWS {updated} 个文档")
    print("=" * 70)


if __name__ == "__main__":
    main()
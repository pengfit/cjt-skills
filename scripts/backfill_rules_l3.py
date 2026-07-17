#!/usr/bin/env python3
"""从 ES DWS 反哺规则 DB 的 l3 字段

2026-07-17: 26,448 条老规则 l3 全是空(列刚加,历史数据未填),
从 dws_<city>_price.breed → category_l3 聚合映射,UPDATE 回写规则 DB。

逻辑:
  1. 跨 20 城 dws_*_price 聚合 breed + category_l3(取众数)
  2. 批量 UPDATE breed_spec_rules SET l3 = ? WHERE breed = ? AND l3 = ''
  3. 事务包装,失败回滚
  4. 输出统计:反哺条数 / 剩余空 l3 数 / 唯一 breed 数
"""
import json
import sqlite3
import sys
import urllib.request
from collections import Counter
from pathlib import Path

# 路径
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
ES_HOST = "http://localhost:59200"
RULES_DB = PROJECT_ROOT / "data" / "breed_spec_rules.db"

# 20 城列表
CITIES = ["xian", "sichuan", "chongqing", "jinan", "rizhao", "henan", "heze",
          "qingdao", "weihai", "hainan", "huhehaote", "hunan", "jiangxi",
          "jilin", "ningxia", "qinghai", "shaanxi", "shanxi", "xinjiang", "guizhou"]


def fetch_breed_l3_from_city(city: str) -> dict:
    """从单城 dws 聚合 breed → category_l3 映射(取众数)"""
    idx = f"dws_{city}_price"
    # 分组聚合:按 breed 分组,每组内 category_l3 取 top 1(众数)
    q = {
        "size": 0,
        "aggs": {
            "by_breed": {
                "terms": {"field": "breed", "size": 10000},
                "aggs": {
                    "top_l3": {
                        "terms": {"field": "category_l3", "size": 1}
                    }
                }
            }
        }
    }
    req = urllib.request.Request(
        f"{ES_HOST}/{idx}/_search",
        data=json.dumps(q).encode(),
        headers={"Content-Type": "application/json"}
    )
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
    except Exception as e:
        print(f"  [{city}] ES 拉取失败: {e}")
        return {}

    breed_to_l3 = {}
    for b in resp["aggregations"]["by_breed"]["buckets"]:
        breed = b["key"]
        if not breed or breed == "（空）":
            continue
        l3_buckets = b["top_l3"]["buckets"]
        if not l3_buckets:
            continue
        l3 = l3_buckets[0]["key"]
        if not l3 or l3 == "UNCLASSIFIED":
            continue
        breed_to_l3[breed] = l3

    return breed_to_l3


def main():
    # Step 1: 跨城聚合(同一 breed 在多城出现时,后到的覆盖;实际多数只有一城有)
    print("=" * 60)
    print(f"Step 1: 跨 20 城聚合 breed → category_l3")
    print("=" * 60)
    global_breed_to_l3 = {}
    for city in CITIES:
        m = fetch_breed_l3_from_city(city)
        print(f"  [{city:12s}] 拿到 {len(m):4d} 条 breed → l3 映射")
        for breed, l3 in m.items():
            # 多城出现时,后到的覆盖(可改为多数投票,但通常一致)
            if breed not in global_breed_to_l3:
                global_breed_to_l3[breed] = l3

    print(f"\n合并后唯一 breed 数: {len(global_breed_to_l3)}")

    # Step 2: UPDATE 规则 DB
    print("\n" + "=" * 60)
    print(f"Step 2: UPDATE breed_spec_rules.l3(事务)")
    print("=" * 60)
    if not RULES_DB.exists():
        print(f"❌ DB 不存在: {RULES_DB}")
        sys.exit(1)

    conn = sqlite3.connect(RULES_DB, timeout=60)
    try:
        # 统计反哺前
        before_empty = conn.execute(
            "SELECT COUNT(*) FROM breed_spec_rules WHERE l3 IS NULL OR l3 = ''"
        ).fetchone()[0]
        before_total = conn.execute("SELECT COUNT(*) FROM breed_spec_rules").fetchone()[0]
        print(f"  反哺前: 总 {before_total} 条, 空 l3 = {before_empty} 条")

        # 事务 UPDATE
        total_updated = 0
        not_mapped = []
        cur_before = before_empty
        for breed, l3 in global_breed_to_l3.items():
            cur = conn.execute(
                "UPDATE breed_spec_rules SET l3 = ? WHERE breed = ? AND (l3 IS NULL OR l3 = '')",
                (l3, breed)
            )
            total_updated += cur.rowcount

        conn.commit()

        # 统计反哺后
        after_empty = conn.execute(
            "SELECT COUNT(*) FROM breed_spec_rules WHERE l3 IS NULL OR l3 = ''"
        ).fetchone()[0]
        after_filled = before_total - after_empty

        print(f"  反哺后: 总 {before_total} 条, 空 l3 = {after_empty} 条")
        print(f"\n  ✅ 反哺 {total_updated} 条规则获得 l3")
        print(f"  📊 反哺率: {total_updated*100/before_empty:.1f}% (空 l3 → 填充)")

        # l3 分布
        print(f"\n  反哺后 l3 分布(TOP 15):")
        rows = conn.execute("""
            SELECT CASE WHEN l3 IS NULL OR l3='' THEN '<空>' ELSE l3 END as l3_val, COUNT(*) as n
            FROM breed_spec_rules GROUP BY l3_val ORDER BY n DESC LIMIT 15
        """).fetchall()
        for l3_val, n in rows:
            print(f"    {l3_val:20s} {n:6,}")

    except Exception as e:
        conn.rollback()
        print(f"❌ 失败,已回滚: {e}")
        sys.exit(1)
    finally:
        conn.close()

    print("\n" + "=" * 60)
    print("✅ backfill 完成,API 刷新即可看到 l3_options 和 l3 列")
    print("=" * 60)


if __name__ == "__main__":
    main()
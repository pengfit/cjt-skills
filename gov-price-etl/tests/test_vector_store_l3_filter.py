#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_vector_store_l3_filter.py
VecStore.search() 的 L3 + breed 严格匹配回归测试。

验证 v0.17+ 改动:
  - query 有 l3 → 只召回 rule.l3 == query.l3 的规则(严格相等,空 l3 不参与)
  - query 有 breed → 只召回 rule.breed == query.breed 的规则('通用' 不参与)
  - 其他 L3 / breed 的规则不得出现在结果里(防止窜料或逃逸)
  - query 无 l3/breed → 原有行为不变

运行:
  cd ~/.openclaw/workspace/cjt/skills/gov-price-etl
  python3 tests/test_vector_store_l3_filter.py

依赖: breed_spec_rules.db(从 gov-price-etl 数据目录读取)
"""
import sys, os, tempfile, sqlite3, shutil
from pathlib import Path

# 把项目根加进 sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gov_price_etl.parse_spec.rules.vector_store import VecStore


# ── 测试用临时 DB ──────────────────────────────────────────────────────────

def _build_test_db() -> str:
    """建一个内存式临时 DB,装 6 条规则,覆盖各种 L3 组合。"""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    con = sqlite3.connect(db_path)
    con.executescript("""
        CREATE TABLE breed_spec_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern TEXT NOT NULL,
            attr TEXT NOT NULL,
            note TEXT DEFAULT '',
            code TEXT DEFAULT '',
            breed TEXT NOT NULL DEFAULT '',
            l3 TEXT DEFAULT '',
            tokens TEXT DEFAULT '[]',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(pattern, attr, breed, l3)
        );
        CREATE TABLE breed_category_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            breed TEXT UNIQUE NOT NULL,
            category TEXT NOT NULL,
            source TEXT DEFAULT 'ai',
            confidence REAL DEFAULT 1.0,
            note TEXT DEFAULT '',
            created_at TEXT DEFAULT (date('now'))
        );
    """)
    # 装 6 条测试规则
    # rule.id | attr    | breed    | l3          | pattern       | code
    test_rules = [
        # 1. 钢化玻璃 L3 精确匹配规则(thickness)
        ("thickness", "浮法玻璃", "钢化玻璃",
         r"(\d+)mm",  "m=re.search(r'(\\d+)mm',s); result['thickness']=m.group(1) if m else ''"),
        # 2. 瓷砖 L3 规则(thickness,同 attr,同 breed 缺)→ 窜料测试用
        ("thickness", "瓷砖", "陶瓷砖",
         r"厚\s*(\d+)",  "m=re.search(r'厚\\s*(\\d+)',s); result['thickness']=m.group(1) if m else ''"),
        # 3. 钢化玻璃 L3 规则(width)→ 应能召回
        ("width", "浮法玻璃", "钢化玻璃",
         r"宽\s*(\d+)",  "m=re.search(r'宽\\s*(\\d+)',s); result['width']=m.group(1) if m else ''"),
        # 4. 空 L3 规则(通配)
        ("diameter", "通用", "",
         r"DN\s*(\d+)",  "m=re.search(r'DN\\s*(\\d+)',s); result['diameter']=m.group(1) if m else ''"),
        # 5. 其他 L3 规则(l3='陶瓷砖')
        ("thickness", "瓷砖", "陶瓷砖",
         r"厚\s*(\d+)\s*mm",  "m=re.search(r'厚\\s*(\\d+)mm',s); result['thickness']=m.group(1) if m else ''"),
        # 6. 完全无 L3 无 breed 规则
        ("height", "", "",
         r"高\s*(\d+)",  "m=re.search(r'高\\s*(\\d+)',s); result['height']=m.group(1) if m else ''"),
    ]
    for attr, breed, l3, pat, code in test_rules:
        con.execute(
            "INSERT INTO breed_spec_rules (pattern, attr, breed, l3, code) VALUES (?,?,?,?,?)",
            (pat, attr, breed, l3, code)
        )
    con.commit()
    con.close()
    return db_path


def _assert(cond: bool, msg: str):
    if not cond:
        print(f"  ✗ FAIL: {msg}")
        sys.exit(1)
    print(f"  ✓ {msg}")


# ── 测试用例 ────────────────────────────────────────────────────────────────

def test_l3_hard_filter_excludes_other_l3():
    """核心测试:query.l3='钢化玻璃' 时,陶瓷砖的规则绝不能出现。"""
    print("\n[Test 1] L3 硬过滤:其他 L3 规则不出现在结果")
    db = _build_test_db()
    vs = VecStore(db_path=db)

    rules = vs.search(spec="厚5mm", breed="浮法玻璃", l3="钢化玻璃", top_k=20)
    rule_l3s = [(r["l3"], r["breed"], r["attr"]) for _, r in rules]

    # 期望:只有 l3='钢化玻璃' 或 l3='' 的规则
    for l3_val, breed_val, attr_val in rule_l3s:
        _assert(
            l3_val == "钢化玻璃" or l3_val == "",
            f"规则 (l3={l3_val!r}, breed={breed_val!r}, attr={attr_val!r}) 应出局"
        )

    print(f"  共召回 {len(rules)} 条,全部 l3 命中或空")
    print(f"  结果: {rule_l3s}")


def test_l3_match_returns_rule():
    """query.l3 精确匹配时,对应规则必须召回。"""
    print("\n[Test 2] L3 精确匹配召回")
    db = _build_test_db()
    vs = VecStore(db_path=db)

    rules = vs.search(spec="宽 1200", breed="浮法玻璃", l3="钢化玻璃", top_k=20)
    attrs = [r["attr"] for _, r in rules]

    _assert("width" in attrs, f"width 应在结果中(实际={attrs})")


def test_no_l3_keeps_old_behavior():
    """query 没传 l3 时,L3 硬过滤不生效,跨 L3 规则都能召回。"""
    print("\n[Test 3] 无 L3 查询:跨 L3 规则不强制隔振")
    db = _build_test_db()
    vs = VecStore(db_path=db)

    # 不传 l3,breed='',避免其他过滤干扰,验证跨 L3 规则都能召回
    rules = vs.search(spec="", breed="", top_k=100)
    l3_set = set(r["l3"] for _, r in rules)
    print(f"  召回 l3 集合: {l3_set}")

    # query 不传 l3 → 钢化玻璃 / 陶瓷砖 / 空 l3 全部参与召回
    _assert("钢化玻璃" in l3_set, "无 l3 查询应召回 l3='钢化玻璃' 规则")
    _assert("陶瓷砖" in l3_set, "无 l3 查询应召回 l3='陶瓷砖' 规则(跨 L3 不拦)")
    _assert("" in l3_set, "无 l3 查询应召回空 l3 规则")


def test_l3_filter_excludes_empty_l3_wildcard():
    """rule.l3='' 的通配规则在 query.l3 命中时不再召回(v0.17+ 严格模式)。"""
    print("\n[Test 4] rule.l3='' 通配规则在 L3 过滤下被排除")
    db = _build_test_db()
    vs = VecStore(db_path=db)

    # query 有 l3='钢化玻璃',rule 4 的 l3='' 不应再被召回
    rules = vs.search(spec="DN15", breed="", l3="钢化玻璃", top_k=20)
    attrs = [r["attr"] for _, r in rules]
    l3_vals = [r["l3"] for _, r in rules]
    print(f"  召回 attrs={attrs}, l3 列表={l3_vals}")

    _assert("" not in l3_vals, "空 l3 规则不应召回(严格模式)")
    _assert("diameter" not in attrs, "rule.l3='' 的 diameter 规则不再作为通配召回")


def test_breed_通用_not_recalled():
    """breed='通用' 规则不应被召回(v0.17+ 严格模式)。"""
    print("\n[Test 6] breed='通用' 不参与召回")
    db = _build_test_db()
    vs = VecStore(db_path=db)

    # query breed='浮法玻璃',rule 4 的 breed='通用' 不应召回
    rules = vs.search(spec="DN15", breed="浮法玻璃", l3="", top_k=20)
    breeds = [r["breed"] for _, r in rules]
    print(f"  召回 breed 列表: {breeds}")

    _assert("通用" not in breeds, "breed='通用' 的规则不应召回(严格模式)")


def test_l3_mismatch_returns_no_match():
    """L3 不匹配 + 没有通配规则时,返回空(不让窜料)。"""
    print("\n[Test 5] L3 不匹配 + 无通配 → 召回为空")
    db = _build_test_db()
    vs = VecStore(db_path=db)

    # query.l3='钢化玻璃',rule 5 (陶瓷砖),rule 2 (陶瓷砖) 都不该出现
    # rule 6 (空 L3 空 breed) 应召回(通配)
    rules = vs.search(spec="高 3m", breed="", l3="钢化玻璃", top_k=20,
                       validate_spec="高 3m")
    l3_set = set(r["l3"] for _, r in rules)
    breed_set = set(r["breed"] for _, r in rules)
    print(f"  召回 l3 集合: {l3_set}, breed 集合: {breed_set}")

    _assert("陶瓷砖" not in l3_set, "陶瓷砖 L3 规则不该出现")
    _assert("瓷砖" not in breed_set, "瓷砖 breed 规则不该出现")


# ── 入口 ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("VecStore L3 + breed 严格匹配回归测试 (v0.17+)")
    print("=" * 60)
    try:
        test_l3_hard_filter_excludes_other_l3()
        test_l3_match_returns_rule()
        test_no_l3_keeps_old_behavior()
        test_l3_filter_excludes_empty_l3_wildcard()
        test_l3_mismatch_returns_no_match()
        test_breed_通用_not_recalled()
        print("\n" + "=" * 60)
        print("✅ 全部 6 个测试通过")
        print("=" * 60)
        return 0
    except SystemExit as e:
        return e.code


if __name__ == "__main__":
    sys.exit(main())
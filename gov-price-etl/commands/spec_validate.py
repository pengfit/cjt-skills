#!/usr/bin/env python3
"""spec_validate.py - 运行规格解析测试集，输出通过率 + 失败详情"""
import argparse, json, os, sys
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from parse_spec import get_parser


def load_testset(path=None):
    if path is None:
        path = os.path.join(SCRIPT_DIR, "spec_testset.json")
    with open(path) as f:
        return json.load(f)


def run_validation(city="xian", detail=False):
    parser = get_parser(city)
    data = load_testset()
    cases = data["test_cases"]
    passed = 0
    failed = []
    for tc in cases:
        spec = tc["spec"]
        expected = tc.get("expected", {})
        got = parser.parse(spec)
        if set(expected.items()) == set(got.items()):
            passed += 1
        else:
            failed.append({"spec": spec, "category": tc.get("category", ""),
                           "expected": expected, "got": got})
    total = len(cases)
    pass_rate = passed / total * 100 if total > 0 else 0
    if detail:
        for tc in cases:
            spec = tc["spec"]
            expected = tc.get("expected", {})
            got = parser.parse(spec)
            status = "✅" if set(expected.items()) == set(got.items()) else "❌"
            print(f"  {status} [{spec}] expected={expected} got={got}")
    print(f"\n[{city}] {passed}/{total} 通过 ({pass_rate:.1f}%)")
    if failed:
        print(f"\n失败 {len(failed)} 条:")
        for f in failed:
            print(f"  [{f['spec']}] expected={f['expected']} got={f['got']}")
    return {"total": total, "passed": passed, "failed_count": len(failed),
            "pass_rate": round(pass_rate, 1), "failed_cases": failed}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="xian")
    ap.add_argument("--detail", action="store_true")
    run_validation(**vars(ap.parse_args()))

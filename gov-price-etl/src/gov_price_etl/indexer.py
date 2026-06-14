"""indexer.py - 索引创建 / 模板管理

幂等创建/更新 gov_dwd / gov_dws 两个 index template，并确保指定索引存在。
"""
from .es_client import get_es_client
from .mappings import build_dwd_mapping, build_dws_mapping


def setup_index_templates(es_host: str) -> None:
    """幂等创建/更新 gov_dwd / gov_dws 两个 index template。"""
    s = get_es_client(es_host)
    for name, pattern, mapping in [
        ("gov_dwd", "dwd_*", build_dwd_mapping()),
        ("gov_dws", "dws_*", build_dws_mapping()),
    ]:
        r = s.put(
            f"{es_host}/_index_template/{name}",
            json={
                "index_patterns": [pattern],
                "template": {"settings": mapping["settings"], "mappings": mapping["mappings"]},
                "priority": 100,
            },
        )
        tag = "OK" if r.status_code in (200, 201) else f"FAIL {r.status_code}"
        print(f"  [template] {name} → {pattern} {tag}")


def ensure_indices(es_host: str, cfg: dict) -> None:
    """统一入口：确保 dwd/dws 索引存在，新建时自动套用 index template。"""
    setup_index_templates(es_host)
    dwd_idx, dws_idx = cfg["dwd"], cfg["dws"]
    s = get_es_client(es_host)
    for idx in (dwd_idx, dws_idx):
        r = s.head(f"{es_host}/{idx}")
        if r.status_code == 404:
            print(f"  [idx] 创建索引 {idx} ...")
            s.put(f"{es_host}/{idx}", json={})  # template 自动套用
            print(f"  [idx] {idx} 创建完成（套用 template）")


# ── backward compat stubs ──────────────────────────────────────────────
def ensure_dwd(es_host: str, dwd_index: str):
    pass  # now handled by ensure_indices


def ensure_dws(es_host: str, dws_index: str):
    pass  # now handled by ensure_indices

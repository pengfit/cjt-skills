#!/usr/bin/env python3
"""etl.py - gov-price ETL 主程序

从 5 个 ods_* 索引读取原始数据，清洗品种/规格/单位，
计算分类，写入 dwd_{city}_price。

用法:
    python3 etl.py                    # 全量（所有城市）
    python3 etl.py --city sichuan     # 只处理指定城市
    python3 etl.py --incremental      # 增量（根据 update_date）
    python3 etl.py --dry-run          # 预览（前100条）
"""

import argparse
import json
import time
import sys
import os
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

try:
    import requests
    import yaml
except ImportError:
    print("请安装依赖: pip3 install requests pyyaml")
    sys.exit(1)

from classify import classify_breed, _fetch_ai_category_batch
from parse_spec import parse_spec, get_parser
from parse_spec.base import clean_spec
from clean import clean_breed, clean_unit, clean_price

# ─── category → category_system 映射 ────────────────────────────────────────
_CATEGORY_CODE_MAP: dict[str, str] = {}
_CATEGORY_NAME_MAP: dict[str, str] = {}  # code → name

def _load_category_system_map() -> tuple[dict[str, str], dict[str, str]]:
    """从 category_in_system.json 构建 category name → code 和 name 映射。"""
    rules_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(rules_dir, "classify", "rules", "category_in_system.json")
    code_map: dict[str, str] = {}
    name_map: dict[str, str] = {}
    if os.path.exists(json_path):
        with open(json_path) as f:
            data = json.load(f)
        for group in data.get("categories", []):
            for child in group.get("children", []):
                code_map[child["name"]] = child["code"]
                name_map[child["code"]] = child["name"]
    return code_map, name_map

def _get_category_system_maps() -> tuple[dict[str, str], dict[str, str]]:
    global _CATEGORY_CODE_MAP, _CATEGORY_NAME_MAP
    if not _CATEGORY_CODE_MAP:
        _CATEGORY_CODE_MAP, _CATEGORY_NAME_MAP = _load_category_system_map()
    return _CATEGORY_CODE_MAP, _CATEGORY_NAME_MAP

def _get_category_system_map() -> dict[str, str]:
    code_map, _ = _get_category_system_maps()
    return code_map

def _get_category_system_name_map() -> dict[str, str]:
    _, name_map = _get_category_system_maps()
    return name_map

# ─── AI 分类结果缓存（进程内，同一 breed 不重复调用 AI）───────────────────────
def load_config():
    cfg_path = os.path.join(os.path.dirname(SCRIPT_DIR), "config.yml")
    with open(cfg_path) as f:
        return yaml.safe_load(f)


def get_es_client(host: str):
    s = requests.Session()
    s.trust_env = False  # 禁用系统代理（macOS "Web Proxy" 配置会被 requests 自动读取）
    return s


# ─── 城市配置 ────────────────────────────────────────────────────────────────
CITY_CONFIGS = {
    "xian": {
        "ods": "ods_material_xian_price",
        "dwd": "dwd_xian_price",
        "dws": "dws_xian_price",
        "city_label": "西安",
    },
    "sichuan": {
        "ods": "ods_material_sichuan_price",
        "dwd": "dwd_sichuan_price",
        "dws": "dws_sichuan_price",
        "city_label": "四川",
    },
    "chongqing": {
        "ods": "ods_material_chongqing_price",
        "dwd": "dwd_chongqing_price",
        "dws": "dws_chongqing_price",
        "city_label": "重庆",
    },
    "jinan": {
        "ods": "ods_material_jinan_price",
        "dwd": "dwd_jinan_price",
        "dws": "dws_jinan_price",
        "city_label": "济南",
    },
    "rizhao": {
        "ods": "ods_material_rizhao_price",
        "dwd": "dwd_rizhao_price",
        "dws": "dws_rizhao_price",
        "city_label": "日照",
    },
    "henan": {
        "ods": "ods_material_henan_price",
        "dwd": "dwd_henan_price",
        "dws": "dws_henan_price",
        "city_label": "河南",
    },
}



# ─── 单条转换 ────────────────────────────────────────────────────────────────
def transform_doc(raw: dict, source_index: str, city: str) -> dict:
    """将一条 ODS 原始文档清洗为 DWD 格式"""
    breed_raw = raw.get("breed", "")
    spec_raw = raw.get("spec", "")
    unit_raw = raw.get("unit", "")

    breed_clean = clean_breed(breed_raw)
    spec_clean = spec_raw
    unit_clean = clean_unit(unit_raw)
    category = classify_breed(breed_clean, spec_clean)

    price = clean_price(raw.get("price")) or 0.0
    tax_price = clean_price(raw.get("tax_price")) or 0.0
    # Crawler bug: when is_tax="0" (不含税), wrote 不含税价 to tax_price, left price=0
    # Fix: if price==0 but tax_price has value, use tax_price as the price
    if price == 0.0 and tax_price > 0:
        price = tax_price
        tax_price = 0.0

    parser = get_parser(city)
    # breed_raw 用于查规则库（规则里存的是原始格式），breed_clean 用于分类/展示
    spec_parsed = parser.parse(spec_clean, breed_raw, category)
    if not spec_parsed:
        # 回退：用 clean_breed 再查一次（部分规则可能用 clean 格式录入）
        spec_parsed = parser.parse(spec_clean, breed_clean, category)

    flat_attr = {k: v for k, v in spec_parsed.items() if v}
    # DWD 统一用 nested attr 格式存储，与 DWS 保持一致
    nested_attr = [{"k": k, "v": v} for k, v in flat_attr.items()]

    return {
        "breed": breed_raw,
        "breed_clean": breed_clean,
        "spec": spec_clean,
        "unit": unit_clean,
        "price": price,
        "tax_price": tax_price,
        "category": category,
        "category_system": _get_category_system_map().get(category, ""),
        "category_system_name": _get_category_system_name_map().get(_get_category_system_map().get(category, ""), ""),
        "province": raw.get("province", ""),
        "city": raw.get("city", ""),
        "county": raw.get("county", ""),
        "tab_type": raw.get("tab_type", ""),
        "tab_name": raw.get("tab_name", ""),
        "update_date": raw.get("update_date", ""),
        "publish_time": raw.get("publish_time", ""),
        "period": raw.get("period", ""),
        "code": raw.get("code", ""),
        "source": raw.get("source", ""),
        "citywide_category": raw.get("category", ""),  # 城市材料分类（建安工程材料等），区别于 classify_breed 的 category
        "source_index": source_index,
        "etl_time": datetime.now().isoformat(),
        "attr": nested_attr,
    }


def ensure_indices(es_host: str, cfg: dict):
    """统一入口：确保 dwd/dws 索引存在，新建时自动套用 index template。"""
    _setup_index_templates(es_host)
    dwd_idx, dws_idx = cfg["dwd"], cfg["dws"]
    s = get_es_client(es_host)
    for idx in (dwd_idx, dws_idx):
        r = s.head(f"{es_host}/{idx}")
        if r.status_code == 404:
            print(f"  [idx] 创建索引 {idx} ...")
            s.put(f"{es_host}/{idx}", json={})  # template 自动套用
            print(f"  [idx] {idx} 创建完成（套用 template）")


def _setup_index_templates(es_host: str):
    """幂等创建/更新 gov_dwd / gov_dws 两个 index template。"""
    for name, pattern, mapping in [
        ("gov_dwd", "dwd_*", _build_dwd_mapping()),
        ("gov_dws", "dws_*", _build_dws_mapping()),
    ]:
        r = get_es_client(es_host).put(f"{es_host}/_index_template/{name}", json={
            "index_patterns": [pattern],
            "template": {"settings": mapping["settings"], "mappings": mapping["mappings"]},
            "priority": 100,
        })
        tag = "OK" if r.status_code in (200, 201) else f"FAIL {r.status_code}"
        print(f"  [template] {name} → {pattern} {tag}")


def _build_dwd_mapping():
    base = {
        "breed":           {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
        "breed_clean":     {"type": "keyword"},
        "spec":            {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
        "unit":            {"type": "keyword"},
        "price":           {"type": "float"},
        "tax_price":       {"type": "float"},
        "category":        {"type": "keyword"},
        "category_system": {"type": "keyword"},
        "category_system_name": {"type": "keyword"},
        "province":        {"type": "keyword"},
        "city":            {"type": "keyword"},
        "county":          {"type": "keyword"},
        "tab_type":        {"type": "keyword"},
        "tab_name":        {"type": "keyword"},
        "update_date":     {"type": "keyword"},
        "publish_time":    {"type": "date", "format": "strict_date_optional_time||epoch_millis", "ignore_malformed": True},
        "period":          {"type": "text"},
        "code":            {"type": "keyword"},
        "source_index":    {"type": "keyword"},
        "etl_time":        {"type": "date", "format": "strict_date_optional_time||epoch_millis", "ignore_malformed": True},
        # attr nested 字段：统一存储解析后的规格参数，与 DWS 保持一致
        "attr": {
            "type": "nested",
            "properties": {"k": {"type": "keyword"}, "v": {"type": "keyword"}},
        },
    }
    return {"mappings": {"properties": base, "dynamic": True}, "settings": {"number_of_shards": 1, "number_of_replicas": 0}}

def _build_dws_mapping():
    base = {
        "spec":              {"type": "text"},
        "breed":             {"type": "keyword"},
        "breed_clean":       {"type": "keyword"},
        "category":          {"type": "keyword"},
        "category_system":   {"type": "keyword"},
        "category_system_name": {"type": "keyword"},
        "unit":              {"type": "keyword"},
        "price":             {"type": "float"},
        "tax_price":         {"type": "float"},
        "region":            {"type": "keyword"},
        "county":            {"type": "keyword"},
        "city":              {"type": "keyword"},
        "province":          {"type": "keyword"},
        "date":              {"type": "date"},
        "update_date":       {"type": "keyword"},
        "etl_time":          {"type": "date"},
        "publish_time":      {"type": "date"},
        "code":              {"type": "keyword"},
        "tab_type":          {"type": "keyword"},
        "tab_name":          {"type": "keyword"},
        "period":            {"type": "text"},
        "source":            {"type": "keyword"},
        "citywide_category": {"type": "keyword"},
        "source_index":      {"type": "keyword"},
        "attr": {
            "type": "nested",
            "properties": {"k": {"type": "keyword"}, "v": {"type": "keyword"}},
        },
    }
    return {"mappings": {"properties": base}, "settings": {"number_of_shards": 1, "number_of_replicas": 0}}


# ── backward compat stubs (keep signatures so existing callers don't break) ──
def ensure_dwd(es_host: str, dwd_index: str):
    pass  # now handled by ensure_indices


def ensure_dws(es_host: str, dws_index: str):
    pass  # now handled by ensure_indices

def bulk_index(es_host: str, index: str, docs: list, ids: list = None, timeout: int = 60) -> tuple:
    if not docs:
        return 0, 0
    session = get_es_client(es_host)
    body = ""
    for i, doc in enumerate(docs):
        # 优先用 ids 里的 _id（来自 ODS 的真实 _id），确保 ai_pending 更新时能命中
        _id = ids[i] if (ids and i < len(ids) and ids[i]) else None
        action = {"index": {"_id": _id}} if _id else {"index": {}}
        body += json.dumps(action, ensure_ascii=False) + "\n"
        body += json.dumps(doc, ensure_ascii=False) + "\n"

    resp = session.post(f"{es_host}/{index}/_bulk", data=body.encode("utf-8"),
                        headers={"Content-Type": "application/x-ndjson"},
                        timeout=timeout)
    result = resp.json()
    errors = sum(1 for item in result.get("items", []) if "error" in item.get("index", {}))
    ok = len(docs) - errors
    return ok, errors


def _build_attr(doc: dict) -> dict:
    """从 DWD 文档中提取 attr 字段（扁平 dict，仅保留非空值）。

    优先提取 nested attr 字段（新格式），同时兼容 attr_* 前缀字段和顶层扁平字段（历史遗留）。
    """
    attr = {}

    # 标准路径 1：nested attr 字段（当前 transform_doc 写入的格式）
    nested = doc.get("attr")
    if nested and isinstance(nested, list):
        for item in nested:
            if isinstance(item, dict):
                k = item.get("k", "")
                v = item.get("v", "")
                if k and v and str(v).lower() not in ("", "null", "none"):
                    attr[k] = str(v)

    # 标准路径 2：attr_* 前缀字段（旧格式 ETL 写入）
    if not attr:
        for f, v in doc.items():
            if not f.startswith("attr_"):
                continue
            if v is None:
                continue
            s = str(v).strip()
            if s and s.lower() not in ("", "null", "none"):
                attr[f[5:]] = s  # strip "attr_" (5 chars) prefix → diameter, grade, ...

    # 兼容路径：顶层扁平字段（手动修复或历史遗留）
    if not attr:
        TOPO_FIELDS = (
            "diameter", "diameter_range",
            "thickness", "length", "width", "height",
            "material", "grade", "pressure", "color", "series",
            "temperature", "voltage", "current", "cores",
            "form", "surface", "fire_rating", "ip_rating",
            "ring_stiffness", "cross_section", "inner_diameter",
            "wall_thickness", "fiber_core", "cable_length",
            "channels", "doors", "media", "range", "output",
            "asphalt_type", "cement_content", "temp_range",
            "humidity_range", "length_range", "height_range",
            "drain_type", "inlet_type", "installation_type",
        )
        for f in TOPO_FIELDS:
            v = doc.get(f)
            if v is None:
                continue
            s = str(v).strip()
            if s and s.lower() not in ("", "null", "none"):
                attr[f] = s
    return attr


def _flat_attr_to_nested(flat: dict) -> list:
    """将扁平 attr dict 转为 nested [{k, v}] 列表，用于写入 DWS。"""
    return [{"k": k, "v": v} for k, v in flat.items() if v]


def flush_to_dws_with_ai(es_host: str, city: str, cfg: dict, batch_size: int = 500, ai_batch_size: int = 100, category: str = "") -> tuple:
    """
    同步 DWD → DWS，附带批量 AI 解析补全 attr。

    流程：
      1. 从 DWD 捞 spec 非空文档
      2. 先用规则库（本地 parse）尝试解析
      3. 规则库解析失败的 doc，攒 batch 调 AI 补全 attr
      4. AI 补全后回写 DWD，再同步到 DWS

    返回 (成功数, 失败数)。
    """
    import sys
    sys.path.insert(0, SCRIPT_DIR)
    try:
        from parse_spec import get_parser
    except Exception:
        get_parser = None

    dwd_idx = cfg["dwd"]
    dws_idx = cfg["dws"]
    session = get_es_client(es_host)

    # 启用 _id 字段排序支持（search_after 需要 etl_time+_id 联合排序打破 tie）
    try:
        requests.put(
            f"{es_host}/_cluster/settings",
            json={"persistent": {"indices.id_field_data.enabled": "true"}},
        )
    except Exception:
        pass

    must_clauses = [{"exists": {"field": "spec"}}]
    if category:
        must_clauses.append({"term": {"category": category}})

    ensure_indices(es_host, cfg)

    # 先统计总数
    body_count = {"query": {"bool": {"must": must_clauses}}}
    count_resp = session.post(f"{es_host}/{dwd_idx}/_count", json=body_count, timeout=30)
    total = count_resp.json().get("count", 0) if count_resp.status_code == 200 else 0
    if total == 0:
        print(f"  [DWS+AI] {city}: 无待同步数据")
        return 0, 0
    print(f"  [DWS+AI] {city}: {dwd_idx} → {dws_idx} ({total:,} 条)")

    # 先用本地规则库解析，AI 仅作为补充
    parser = get_parser(city) if get_parser else None
    local_parsed = 0
    local_failed = 0

    synced = 0
    failed = 0
    ai_parsed = 0
    ai_failed = 0
    pages = 0

    body = {"query": {"bool": {"must": must_clauses}}, "size": batch_size, "sort": [{"etl_time": "asc"}, {"_id": "asc"}]}
    resp = session.post(f"{es_host}/{dwd_idx}/_search", json=body, timeout=60)
    if resp.status_code != 200:
        print(f"  [DWS+AI] 查询 DWD 失败: {resp.text[:200]}")
        return 0, 0
    hits = resp.json()["hits"]["hits"]

    # 待 AI 解析的批次
    ai_batch: list[dict] = []  # [{doc_id, spec, breed, category, index}, ...]

    def _flush_ai_batch():
        nonlocal ai_batch, synced, failed, ai_parsed, ai_failed, local_parsed, local_failed
        if not ai_batch:
            return {}, []
        import urllib.request, urllib.error, json as _json, socket
        # 按 (breed, spec) 去重，保留所有 doc_id
        from collections import defaultdict
        spec_groups: dict[tuple, list] = defaultdict(list)
        for b in ai_batch:
            key = (b["breed"], b["spec"])
            spec_groups[key].append(b)

        deduped = [v[0] for v in spec_groups.values()]
        if len(ai_batch) > len(deduped):
            print(f"    [AI] 去重: {len(ai_batch)} → {len(deduped)} (breed+spec)")

        items = [{"spec": b["spec"], "breed": b["breed"], "category": b["category"]} for b in deduped]

        token = ""
        try:
            with open("/Users/pengfit/.openclaw/openclaw.json") as f:
                token = _json.load(f).get("gateway", {}).get("auth", {}).get("token", "")
        except Exception:
            pass

        # 串行调用 AI（道友要求：AI 部分不要并行）
        AI_BATCH = 20
        TIMEOUT = 300  # 5min，单批 20 条 AI 解析可能需要等待 OpenClaw gateway 排队
        all_results = []

        def _call_ai_sub_batch(sub_items, batch_idx):
            body_req = _json.dumps({"items": sub_items, "write_rules": True}).encode("utf-8")
            req = urllib.request.Request(
                "http://localhost:5200/api/stats/spec-quality/batch-spec-parse",
                data=body_req,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                method="POST",
            )
            # 不走系统代理
            no_proxy_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            try:
                print(f"    [AI] sub-batch {batch_idx}: calling API with {len(sub_items)} items, timeout={TIMEOUT}s...", flush=True)
                with no_proxy_opener.open(req, timeout=TIMEOUT) as r:
                    print(f"    [AI] sub-batch {batch_idx}: response received", flush=True)
                    sub_result = _json.loads(r.read())
                print(f"    [AI] sub-batch {batch_idx}: parsed, ok={sub_result.get('ok')}", flush=True)
                return sub_result.get("results", []) if sub_result.get("ok") else []
            except urllib.error.URLError as e:
                print(f"    [AI] sub-batch {batch_idx} URL error: {e}")
                return []
            except socket.timeout:
                print(f"    [AI] sub-batch {batch_idx} timeout after {TIMEOUT}s")
                return []
            except Exception as e:
                print(f"    [AI] sub-batch {batch_idx} 调用失败: {e}")
                return []

        sub_batches = [items[i:i + AI_BATCH] for i in range(0, len(items), AI_BATCH)]
        print(f"    [AI] 共 {len(sub_batches)} 个 sub-batch，按道友要求串行执行（不开线程池）...", flush=True)
        for i, sb in enumerate(sub_batches):
            results = _call_ai_sub_batch(sb, i+1)
            all_results.extend(results)
        print(f"    [AI] 所有 sub-batch 完成，累计 {len(all_results)} 条结果", flush=True)

        # 构建 breed+spec → parsed attr 的映射
        results_map = {}
        for r in all_results:
            # AI 返回的 breed 全为 null，无法用于匹配；
            # 统一用 "" + spec 作为 key，确保与 ai_batch lookup 时的 (real_breed, spec) 不匹配；
            # 改用纯 spec 作为映射 key（同一个 spec 唯一对应一套 suggestions）
            results_map[r.get("spec", "")] = r.get("suggestions", [])

        skipped = []
        docs_to_sync = []

        for b in ai_batch:
            suggestions = results_map.get(b["spec"], [])
            doc = {"doc_id": b["doc_id"], "spec": b["spec"], "breed": b["breed"], "category": b["category"], "suggestions": suggestions}
            if suggestions:
                docs_to_sync.append(doc)
            else:
                docs_to_sync.append(doc)  # AI 失败也同步，只是 attr 为空

        ai_batch.clear()
        return results_map, docs_to_sync

    # 追踪已处理的 doc_id，避免重复处理（search_after 在所有 doc etl_time 相同时会失效）
    seen_doc_ids = set()


    # 构建 hits 映射，方便 final flush 时查找（page 切换后 hits 会被覆盖）
    hits_by_id: dict = {h["_id"]: h for h in hits}

    prev_etl_time = None
    while hits:
        pages += 1

        for h in hits:
            doc_id = h["_id"]
            if doc_id in seen_doc_ids:
                continue
            seen_doc_ids.add(doc_id)
            d = dict(h["_source"])
            spec = d.get("spec", "")
            breed = d.get("breed", "")
            cat = d.get("category", "")
            hits_by_id[doc_id] = h

            # 优先用本地规则库解析：
            # 1. DWD 已有 attr → 直接 sync 到 DWS，跳过 AI
            # 2. 本地规则库能解析 → 写回 DWD attr，sync 到 DWS
            # 3. 规则库解析失败 → 送 AI
            existing_attr = _build_attr(d)
            if existing_attr:
                # DWD 已有 attr，直接 sync
                nested = _flat_attr_to_nested(existing_attr)
                dws_doc = {**d, "attr": nested}
                for f in list(dws_doc.keys()):
                    if f.startswith("attr_"):
                        dws_doc.pop(f)
                for f in ("date", "publish_time"):
                    if not dws_doc.get(f):
                        dws_doc.pop(f, None)
                ok_s, err_s = bulk_index(es_host, dws_idx, [dws_doc], [doc_id])
                synced += ok_s
                failed += err_s
                local_parsed += 1
                continue

            # 本地规则库尝试解析
            local_attrs: dict = {}
            if parser and spec:
                try:
                    parsed = parser.parse(spec, breed, cat)
                    if parsed:
                        local_attrs = {k: v for k, v in parsed.items() if v}
                except Exception:
                    pass

            if local_attrs:
                # 规则库命中：写回 DWD，sync 到 DWS
                nested = _flat_attr_to_nested(local_attrs)
                upd_body = (
                    json.dumps({"update": {"_id": doc_id}}, ensure_ascii=False) + "\n" +
                    json.dumps({"doc": {"attr": nested}}, ensure_ascii=False) + "\n"
                )
                session.post(
                    f"{es_host}/{dwd_idx}/_bulk",
                    data=upd_body.encode("utf-8"),
                    headers={"Content-Type": "application/x-ndjson"},
                    timeout=60,
                )
                dws_doc = {**d, "attr": nested}
                for f in list(dws_doc.keys()):
                    if f.startswith("attr_"):
                        dws_doc.pop(f)
                for f in ("date", "publish_time"):
                    if not dws_doc.get(f):
                        dws_doc.pop(f, None)
                ok_s, err_s = bulk_index(es_host, dws_idx, [dws_doc], [doc_id])
                synced += ok_s
                failed += err_s
                local_parsed += 1
            else:
                # 规则库未命中，送 AI
                local_failed += 1
                ai_batch.append({"doc_id": doc_id, "spec": spec, "breed": breed, "category": cat})

        # AI batch 满了则触发解析
        if len(ai_batch) >= ai_batch_size:
            results_map, docs_to_sync = _flush_ai_batch()
            for doc in docs_to_sync:
                did = doc["doc_id"]
                suggestions = doc["suggestions"]
                # 回写 DWD attr
                attrs = {}
                for s in suggestions:
                    a = s.get("attr", "")
                    c = s.get("code_block", "")
                    if not a or not c:
                        continue
                    # 防御性规范 attr 名称：统一去掉 attr_ 前缀
                    # 规则库已修复，但 API 未来可能返回不一致的 attr 名
                    norm_a = a[5:] if a.startswith("attr_") else a
                    # 执行 code_block 提取 value
                    try:
                        import re as _re_mod
                        _exec_globals = {"result": {}, "re": _re_mod, "s": doc["spec"]}
                        _code = c if isinstance(c, str) else "\n".join(c)
                        exec(_code, _exec_globals)
                        # 优先用 norm_a 查 result（已修复规则）；兼容旧 result['attr_grade']
                        _val = _exec_globals.get("result", {}).get(norm_a, "")
                        if not _val:
                            _val = _exec_globals.get("result", {}).get(a, "")
                        if _val:
                            attrs[norm_a] = str(_val)
                    except Exception:
                        pass
                upd_body = '\n'.join(
                    json.dumps({"update": {"_id": did}}, ensure_ascii=False) + '\n' +
                    json.dumps({"doc": {"attr": _flat_attr_to_nested(attrs)}}, ensure_ascii=False)
                )
                session.post(f"{es_host}/{dwd_idx}/_bulk", data=upd_body.encode("utf-8"),
                            headers={"Content-Type": "application/x-ndjson"}, timeout=60)
            # 同步到 DWS
            dws_docs, dws_ids = [], []
            import re as _re_mod
            for doc in docs_to_sync:
                did = doc["doc_id"]
                suggestions = doc["suggestions"]
                # 重新执行 code_block 获取 attrs（从 suggestions，不依赖 DWD 回写）
                dws_attrs = {}
                if not suggestions:
                    print(f"  [WARN] no suggestions for spec={doc['spec'][:30]}, doc_id={did[:8]}, breed={doc['breed']}", flush=True)
                for s in suggestions:
                    a = s.get("attr", "")
                    c = s.get("code_block", "")
                    if not a or not c:
                        continue
                    # 防御性规范 attr 名称：统一去掉 attr_ 前缀
                    norm_a = a[5:] if a.startswith("attr_") else a
                    try:
                        _eg = {"result": {}, "re": _re_mod, "s": doc["spec"]}
                        _cd = c if isinstance(c, str) else "\n".join(c)
                        exec(_cd, _eg)
                        # 优先用 norm_a 查 result；兼容旧 result['attr_grade']
                        _v = _eg.get("result", {}).get(norm_a, "")
                        if not _v:
                            _v = _eg.get("result", {}).get(a, "")
                        if _v:
                            dws_attrs[norm_a] = str(_v)
                    except Exception as e:
                        print(f"  [DEBUG] code_block failed for {a}: {e}", flush=True)
                # 从 hits_by_id 找源文档（累积了所有页的 hit 对象）
                h = hits_by_id.get(did)
                if not h:
                    continue
                src = dict(h["_source"])
                if not src:
                    continue
                # 将 dws_attrs 放入 src["attr"]（nested {k,v} 列表）
                # AI 无建议时 fallback：从 DWD 源文档提取 attr_* / 顶层字段
                if not dws_attrs:
                    dws_attrs = _build_attr(src)
                nested_attr = {**dws_attrs}
                # 合并 src 中的 nested attr（旧格式 dict 兼容 or 新格式 list）
                _src_attr = src.get("attr")
                if isinstance(_src_attr, dict):
                    for _ak, _av in _src_attr.items():
                        if _ak not in nested_attr:
                            nested_attr[_ak] = _av
                elif isinstance(_src_attr, list):
                    for _item in _src_attr:
                        if isinstance(_item, dict):
                            _ak = _item.get("k", "")
                            _av = _item.get("v", "")
                            if _ak and _ak not in nested_attr:
                                nested_attr[_ak] = str(_av)
                src["attr"] = _flat_attr_to_nested(nested_attr)
                print(f"  [DEBUG] dws_attrs for spec={doc['spec']}: {dws_attrs}", flush=True)
                for f in list(src.keys()):
                    if f.startswith("attr_"):
                        src.pop(f)
                for f in ("date", "publish_time"):
                    if not src.get(f):
                        src.pop(f, None)
                dws_docs.append(src)
                dws_ids.append(did)
            if dws_docs:
                ok_s, err_s = bulk_index(es_host, dws_idx, dws_docs, dws_ids)
                synced += ok_s
                failed += err_s

        last_hit = hits[-1]
        last_etl_time = last_hit["_source"].get("etl_time", "") or ""
        search_after = [last_etl_time, last_hit["_id"]]
        print(f"  [PAGE] pages={pages}, last_etl_time={repr(last_etl_time)}, last_id={last_hit['_id'][:8]}, hits_this_page={len(hits)}", flush=True)
        body_page = {"query": {"bool": {"must": must_clauses}}, "size": batch_size, "search_after": search_after, "sort": [{"etl_time": "asc"}, {"_id": "asc"}]}
        try:
            resp_page = session.post(f"{es_host}/{dwd_idx}/_search", json=body_page, timeout=60)
        except Exception as e:
            print(f"  [ERROR] search_after request failed: {e}", flush=True)
            break
        if resp_page.status_code != 200:
            print(f"  [ERROR] search_after response status={resp_page.status_code}", flush=True)
            break
        hits = resp_page.json()["hits"]["hits"]
        for h in hits:
            hits_by_id[h["_id"]] = h
        # 检测 search_after 是否卡住（连续两页 last_etl_time 相同 且 hits 非空 = 疑似死循环）
        if pages > 1 and hits and last_etl_time == prev_etl_time:
            print(f"  [WARN] search_after 可能死循环: etl_time={repr(last_etl_time)} 连续相同, hits={len(hits)}, 强制退出", flush=True)
            break
        prev_etl_time = last_etl_time

    # 剩余 AI batch
    if ai_batch:
        results_map, docs_to_sync = _flush_ai_batch()
        dws_docs, dws_ids = [], []
        for doc in docs_to_sync:
            did = doc["doc_id"]
            suggestions = doc["suggestions"]
            # 执行 code_block，提取实际属性值
            attrs = {}
            for s in suggestions:
                a = s.get("attr", "")
                c = s.get("code_block", "")
                if not a or not c:
                    continue
                # 防御性规范 attr 名称：统一去掉 attr_ 前缀
                norm_a = a[5:] if a.startswith("attr_") else a
                try:
                    exec_globals = {"result": {}, "re": __import__("re"), "s": doc["spec"]}
                    exec(c, exec_globals)
                    # 优先用 norm_a 查 result；兼容旧 result['attr_grade']
                    _val = exec_globals.get("result", {}).get(norm_a, "")
                    if not _val:
                        _val = exec_globals.get("result", {}).get(a, "")
                    if _val:
                        attrs[norm_a] = str(_val)
                except Exception as e:
                    pass
            # 更新 DWD（写入实际值，非 code_block）
            if attrs:
                upd_body = (
                    json.dumps({"update": {"_id": did}}, ensure_ascii=False) + "\n" +
                    json.dumps({"doc": attrs}, ensure_ascii=False) + "\n"
                )
                session.post(
                    f"{es_host}/{dwd_idx}/_bulk",
                    data=upd_body.encode("utf-8"),
                    headers={"Content-Type": "application/x-ndjson"},
                    timeout=60,
                )
            # 从 AI 结果构建 attr，直接用于 DWS 同步（不依赖 DWD 写入后再查）
            dws_attr = {k[5:]: v for k, v in attrs.items() if k.startswith("attr_")}
            # AI 无建议时 fallback：从 DWD 源文档提取 attr_* / 顶层字段
            if not dws_attr:
                dws_attr = _build_attr(dict(h["_source"]) if h else {})
            # 从 hits_by_id 找源文档（hit 对象），提取 _source
            h = hits_by_id.get(did)
            if not h:
                h = next((h2 for h2 in hits if h2['_id'] == did), None)
            if not h:
                print(f"  [DEBUG] src not found for {did[:8]}", flush=True)
                continue
            src = dict(h["_source"])
            src["attr"] = _flat_attr_to_nested(dws_attr)
            for f in ("date", "publish_time"):
                if not src.get(f):
                    src.pop(f, None)
            dws_docs.append(src)
            dws_ids.append(did)
        print(f"  [DEBUG] final flush: dws_docs={len(dws_docs)}, dws_ids={len(dws_ids)}", flush=True)
        if dws_docs:
            ok_s, err_s = bulk_index(es_host, dws_idx, dws_docs, dws_ids)
            synced += ok_s
            failed += err_s

    print(f"  [DWS+AI] {city} 完成: synced={synced}, failed={failed}, local_parsed={local_parsed}, local_failed={local_failed}, ai_batch_sent={local_failed}")
    return synced, failed


def flush_to_dws(es_host: str, city: str, cfg: dict, batch_size: int = 500, category: str = "") -> tuple:
    """
    同步 DWD → DWS。

    入池条件：spec 非空。category 不为空时只同步该分类。

    返回 (成功数, 失败数)。
    """
    dwd_idx = cfg["dwd"]
    dws_idx = cfg["dws"]
    session = get_es_client(es_host)

    must_clauses = [{"exists": {"field": "spec"}}]
    if category:
        must_clauses.append({"term": {"category": category}})
    body = {
        "query": {"bool": {"must": must_clauses}},
        "size": batch_size,
        "sort": [{"etl_time": "asc"}, {"_id": "asc"}],
    }

    ensure_indices(es_host, cfg)

    resp = session.post(f"{es_host}/{dwd_idx}/_search", json=body)
    if resp.status_code != 200:
        print(f"  [DWS] 查询 DWD 失败: {resp.text[:200]}")
        return 0, 0

    data = resp.json()
    hits = data["hits"]["hits"]
    total = data["hits"]["total"]
    if isinstance(total, dict):
        total = total.get("value", 0)

    if total == 0:
        print(f"  [DWS] {city}: 无待同步数据")
        return 0, 0

    ensure_indices(es_host, cfg)
    print(f"  [DWS] {city}: {dwd_idx} → {dws_idx} ({total:,} 条待同步)")

    synced = 0
    failed = 0
    pages = 0

    prev_etl_time = None
    while hits:
        pages += 1
        docs, doc_ids = [], []
        for h in hits:
            d = dict(h["_source"])
            # 构建 DWS 的 attr nested（扁平 dict → nested [{k,v}] 列表）
            d["attr"] = _flat_attr_to_nested(_build_attr(d))
            # 删除原顶层 attr_* 字段（已迁移到 attr nested，避免字段冲突
            for f in list(d.keys()):
                if f.startswith("attr_"):
                    d.pop(f)
            # 过滤空 date 字段（空字符串无法解析为 date 类型）
            for f in ("date", "publish_time"):
                if not d.get(f):
                    d.pop(f, None)
            # DWD _id 即 ODS _id，复用于 DWS
            docs.append(d)
            doc_ids.append(h["_id"])

        ok, err = bulk_index(es_host, dws_idx, docs, doc_ids)
        synced += ok
        failed += err

        if ok > 0:
            body = '\n'.join(
                json.dumps({"update": {"_id": did}}, ensure_ascii=False) + "\n" +
                json.dumps({"doc": {}}, ensure_ascii=False)
                for did in doc_ids
            )
            session.post(f'{es_host}/{dwd_idx}/_bulk', data=body.encode('utf-8'),
                        headers={'Content-Type': 'application/x-ndjson'}, timeout=60)

        if pages % 20 == 0:
            print(f"    pages={pages}, synced={synced}/{total}")

        last_hit = hits[-1]
        last_etl_time = last_hit["_source"].get("etl_time", "") or ""
        search_after = [last_etl_time, last_hit["_id"]]
        body_page = {
            "query": {"bool": {"must": must_clauses if must_clauses else [{"match_all": {}}]}},
            "size": batch_size,
            "search_after": search_after,
            "sort": [{"etl_time": "asc"}, {"_id": "asc"}],
        }
        try:
            resp_page = session.post(f"{es_host}/{dwd_idx}/_search", json=body_page, timeout=60)
        except Exception:
            break
        if resp_page.status_code != 200:
            break
        result = resp_page.json()
        hits = result["hits"]["hits"]
        # 检测 search_after 死循环
        if pages > 1 and hits and last_etl_time == prev_etl_time:
            print(f"  [WARN] flush_to_dws search_after 可能死循环: etl_time={repr(last_etl_time)} 连续相同, hits={len(hits)}, 强制退出", flush=True)
            break
        prev_etl_time = last_etl_time

    print(f"  [DWS] {city} 完成: synced={synced}, failed={failed}")
    return synced, failed


# ─── 单城市 ETL ────────────────────────────────────────────────────────────────
def etl_city(es_host: str, city: str, cfg: dict,
             batch_size: int = 500, incremental: bool = False,
             since_date: str = "", dry_run: bool = False,
             category: str = "", mark_done: bool = False) -> tuple:
    ods_idx = cfg["ods"]
    dwd_idx = cfg["dwd"]

    ensure_indices(es_host, cfg)

    session = get_es_client(es_host)
    count_resp = session.get(f"{es_host}/{ods_idx}/_count")
    if count_resp.status_code != 200:
        print(f"  [ETL] {city}: 索引 {ods_idx} 不存在或查询失败，跳过")
        return 0, 0

    total = count_resp.json()["count"]
    if total == 0:
        print(f"  [ETL] {city}: {ods_idx} 为空，跳过")
        return 0, 0

    print(f"  [ETL] {city}: {ods_idx} ({total:,} 条) → {dwd_idx}")

    body = {
        "query": {"bool": {"must": [{"match_all": {}}], "must_not": [{"terms": {"spec": ["/", ""]}}]}},
        "size": min(batch_size, total),
        "sort": [{"update_date": "asc"}],
    }

    if category and not (incremental and since_date):
        body["query"] = {"bool": {"must": [{"term": {"category": category}}], "must_not": [{"terms": {"spec": ["/", ""]}}]}}

    if incremental and since_date:
        if category:
            body["query"] = {"bool": {"must": [{"term": {"category": category}}], "must_not": [{"terms": {"spec": ["/", ""]}}]}}
        else:
            body["query"] = {"bool": {"must": [{"range": {"update_date": {"gte": since_date}}}], "must_not": [{"terms": {"spec": ["/", ""]}}]}}

    resp = session.post(f"{es_host}/{ods_idx}/_search?scroll=2m", json=body)
    if resp.status_code != 200:
        print(f"  [ETL] {city}: 查询失败: {resp.text[:200]}")
        return 0, 0

    data = resp.json()
    hits = data["hits"]["hits"]
    scroll_id = data.get("_scroll_id", "")

    etled = 0
    failed = 0
    pages = 0
    # 收集需要 AI 分类的 (breed_clean, doc_id)
    ai_pending: list[tuple[str, str]] = []

    while hits:
        pages += 1
        docs = []
        doc_ids = []

        for h in hits:
            try:
                doc = transform_doc(h["_source"], ods_idx, city)
                spec_val = doc.get("spec", "")
                if not spec_val or spec_val == "/":
                    continue
                if dry_run:
                    print(f"    [dry-run] {doc['breed_clean']} → {doc['category']}")
                    continue
                # category == "其他" 时先写入 DWD（category="其他"），AI 批量分类后再更新
                if doc["category"] == "其他":
                    ai_pending.append((doc["breed_clean"], h["_id"]))
                    # AI 待分类品种：先写入 DWD（不带 category，等 AI 更新时用 update doc_as_upsert 合并）
                    # 注意：初始写入只有基础字段，AI 更新时会补充完整文档
                    ai_doc = {k: v for k, v in doc.items() if k != "category"}
                    docs.append(ai_doc)
                    doc_ids.append(h["_id"])
                    continue
                docs.append(doc)
                doc_ids.append(h["_id"])
            except Exception as e:
                failed += 1
                if failed <= 3:
                    print(f"    转换失败: {e}")

        if docs and not dry_run:
            ok, fail = bulk_index(es_host, dwd_idx, docs, doc_ids)
            etled += ok
            failed += fail

        if pages % 20 == 0:
            print(f"    pages={pages}, etled={etled}/{total}")

        resp = session.post(f"{es_host}/_search/scroll?scroll=2m",
                             json={"scroll_id": scroll_id})
        if resp.status_code != 200:
            break
        result = resp.json()
        hits = result["hits"]["hits"]
        scroll_id = result.get("_scroll_id", "")

    if scroll_id:
        session.delete(f"{es_host}/_search/scroll", json={"scroll_id": scroll_id})

    # ── 批量 AI 分类 ──
    ai_updated = 0
    if ai_pending and not dry_run:
        breeds = list(dict.fromkeys(b for b, _ in ai_pending))  # 去重保留顺序
        breed_cats: dict = {}
        # 分批调用，每批最多 20 条
        _AI_BATCH_SIZE = 20
        for i in range(0, len(breeds), _AI_BATCH_SIZE):
            chunk = breeds[i:i + _AI_BATCH_SIZE]
            cats = _fetch_ai_category_batch(chunk, city)
            breed_cats.update(cats)
            if i + _AI_BATCH_SIZE < len(breeds):
                import time; time.sleep(0.5)  # 加速：原 10s 改为 0.5s
        if breed_cats:
            # 按 doc_id 分组批量更新
            update_body = ""
            for breed_clean, doc_id in ai_pending:
                cat = breed_cats.get(breed_clean, "其他")
                # 用 update + doc_as_upsert 代替 index：
                # 文档不存在时自动创建（upsert），存在时只更新 category 字段（不覆盖其他字段）
                update_body += json.dumps({"update": {"_id": doc_id}}, ensure_ascii=False) + "\n"
                update_body += json.dumps({
                    "doc": {
                        "category": cat,
                        "category_system": _get_category_system_map().get(cat, ""),
                        "category_system_name": _get_category_system_name_map().get(_get_category_system_map().get(cat, ""), ""),
                    },
                    "doc_as_upsert": True,
                }, ensure_ascii=False) + "\n"
            if update_body:
                _session = get_es_client(es_host)
                r = _session.post(f"{es_host}/{dwd_idx}/_bulk",
                                  data=update_body.encode("utf-8"),
                                  headers={"Content-Type": "application/x-ndjson"})
                result = r.json()
                errors = sum(1 for it in result.get("items", []) if "error" in it.get("update", {}))
                ai_updated = len(ai_pending) - errors
                print(f"  [AI] 批量更新详情: 更新 {ai_updated}/{len(ai_pending)} 条，错误 {errors}")
                if errors > 0:
                    for it in result.get("items", [])[:3]:
                        if "error" in it.get("update", {}):
                            print(f"    错误: {it['update']['error']}")
        print(f"  [AI] 批量分类 {len(ai_pending)} 条 → 更新 {ai_updated} 条")

    print(f"  [ETL] {city} 完成: → {dwd_idx} | etled={etled}, failed={failed}")
    return etled, failed


# ─── 主 ETL ───────────────────────────────────────────────────────────────────
def run_etl(es_host: str, cities: list, batch_size: int = 500,
            incremental: bool = False, since_date: str = "",
            dry_run: bool = False, category: str = "",
            mark_done: bool = False):
    total_etled = 0
    total_failed = 0

    for city in cities:
        if city not in CITY_CONFIGS:
            print(f"[ETL] 未知城市: {city}，跳过")
            continue

        cfg = CITY_CONFIGS[city]
        print(f"\n[ETL] 处理城市: {city} ({cfg['city_label']})")

        ok, fail = etl_city(
            es_host, city, cfg,
            batch_size=batch_size,
            incremental=incremental,
            since_date=since_date,
            dry_run=dry_run,
            category=category,
            mark_done=mark_done,
        )
        total_etled += ok
        total_failed += fail

        dws_ok, dws_fail = flush_to_dws_with_ai(es_host, city, cfg, batch_size=batch_size)
        print(f"  [DWS+AI] {city} 同步结果: ok={dws_ok}, fail={dws_fail}")

    print(f"\n[ETL] 全部完成: etled={total_etled}, failed={total_failed}")
    return total_etled, total_failed


# ─── CLI ────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="gov-price ETL（多城市）")
    parser.add_argument("--city", default="", help=f"指定城市（空=全部）可用: {', '.join(CITY_CONFIGS.keys())}")
    parser.add_argument("--incremental", action="store_true", help="增量模式")
    parser.add_argument("--dry-run", action="store_true", help="预览模式（不写入）")
    parser.add_argument("--since", default="", help="增量起始日期 YYYY-MM-DD")
    parser.add_argument("--category", default="", help="只清洗指定分类（category 字段过滤）")
    parser.add_argument("--batch-size", type=int, default=500, help="批量大小")
    parser.add_argument("--mark-done", action="store_true", help="批量确认规则（直接标记 needs_spec_parse=False，不走 AI）")
    args = parser.parse_args()

    cfg = load_config()
    es_host = cfg["es"]["host"]

    if args.city:
        cities = [args.city] if args.city in CITY_CONFIGS else []
        if not cities:
            print(f"[ETL] 未知城市: {args.city}")
            print(f"可用城市: {', '.join(CITY_CONFIGS.keys())}")
            sys.exit(1)
    else:
        cities = list(CITY_CONFIGS.keys())

    print(f"[ETL] ES: {es_host}")
    print(f"[ETL] 城市: {', '.join(cities)}")
    print(f"[ETL] 模式: {'增量' if args.incremental else '全量'} {'(dry-run)' if args.dry_run else ''}")

    start = time.time()
    ok, fail = run_etl(
        es_host, cities,
        batch_size=args.batch_size,
        incremental=args.incremental,
        since_date=args.since,
        dry_run=args.dry_run,
        mark_done=args.mark_done,
    )
    print(f"[ETL] 耗时 {time.time()-start:.1f}s | ok={ok}, fail={fail}")


if __name__ == "__main__":
    main()
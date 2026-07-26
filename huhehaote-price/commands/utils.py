"""青海建设工程市场价格信息采集 - 工具函数"""
def _resolve_etl_root():
    """解析 gov-price-etl 项目根路径。

    优先级：
      1) 环境变量 GOV_PRICE_ETL_ROOT（部署/调试可显式覆盖）
      2) 自动反推：从本文件路径向上找 'gov-price-etl' 同级目录，
         不依赖硬编码的 workspace 名 / 目录深度。
      3) 兜底扫描：~/.openclaw/workspace/*/skills/gov-price-etl,
         不预设 workspace 名。
      4) 仍找不到：抛错提示用户设环境变量。绝不默默返回错误路径。
    """
    import os
    from pathlib import Path
    env = os.environ.get("GOV_PRICE_ETL_ROOT")
    if env and os.path.isdir(env):
        return env
    p = Path(__file__).resolve().parent
    for _ in range(6):
        candidate = p / "gov-price-etl"
        if candidate.is_dir():
            return str(candidate)
        p = p.parent
    workspace_root = Path.home() / ".openclaw" / "workspace"
    if workspace_root.is_dir():
        for ws in workspace_root.iterdir():
            candidate = ws / "skills" / "gov-price-etl"
            if candidate.is_dir():
                return str(candidate)
    raise FileNotFoundError(
        "找不到 gov-price-etl 项目根。"
        "请设置环境变量 GOV_PRICE_ETL_ROOT 指向项目根，"
        "或确认 ETL 已部署在 <workspace>/skills/gov-price-etl。"
    )


import os
import sys

import yaml

# v0.7 (2026-07-02) P1 抽取：工具函数委托到 gov_price_etl.collectors
_etl_root = _resolve_etl_root()
if os.path.isdir(_etl_root) and _etl_root not in sys.path:
    sys.path.insert(0, _etl_root)
from gov_price_etl.collectors import ( get_es_client, get_s3_client, ensure_bucket,
    upload_to_minio, minio_object_url, fetch_html, download_file,
)

def load_config():
    """加载 skill 根目录的 config.yml"""
    cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.yml')
    with open(cfg_path, encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


# 2026-07-26: 智能拆分 breed/spec — 通用正则 + 领域特例
# 背景：huhehaote PDF 表格里很多「核心名 + 规格」是一次连写的（如「钢筋HPB300(高线)Φ6」），
#       原始 spec 列为空，ETL 会跳过（v0.12+ 源头杜绝设计）。需要提前拆开。
# 设计：先空格拆、再正则抽 Φ/DN/De/Mpa/mm/m³ 、最后走领域特例（玻璃厚度、混凝土标号）。
import re

GENERIC_SPEC_PATTERNS = [
    # Φ6 / Φ12.5 / φ6
    (re.compile(r'Φ(\d+(?:\.\d+)?)'), None),
    (re.compile(r'φ(\d+(?:\.\d+)?)'), None),
    # DN100 / De110
    (re.compile(r'\bDN(\d+)'), None),
    (re.compile(r'\bDe(\d+)'), None),
    # Mpa1.6
    (re.compile(r'Mpa(\d+(?:\.\d+)?)', re.IGNORECASE), None),
    # 240×115×53mm / 6×50mm
    (re.compile(r'(\d+)\s*×\s*(\d+)(?:\s*×\s*(\d+))?\s*mm'), None),
    # 通用 mm / m³ / t (以词边界防误伤“25×6mm”里的 6)
    (re.compile(r'(\d+(?:\.\d+)?)\s*mm\b'), None),
    (re.compile(r'(\d+(?:\.\d+)?)\s*m³\b'), None),
    (re.compile(r'(\d+(?:\.\d+)?)\s*\bt\b'), None),
]


def smart_split_breed_spec(breed: str, spec: str = '') -> tuple[str, str]:
    """智能拆分 breed/spec。返回 (new_breed, new_spec)。

    优先级：
      1. 空格拆分（已有的源 PDF 「核心名 规格」布局）
      2. 通用正则抽 Φ/DN/De/Mpa/mm/m³/t/×mm
      3. 领域特例：玻璃厚度（5+12A+5mm）、混凝土标号+石料（C30 碎石）

    拆到 spec 有内容为止。拿不到就返回原样（spec 可能还是空，让 ETL 拒收）。
    """
    if not breed:
        return breed, spec

    original_breed = breed
    original_spec = spec

    # Step 1: 空格拆分
    if ' ' in breed:
        breed_part, _, space_part = breed.partition(' ')
        breed = breed_part
        if not spec:
            spec = space_part
        else:
            spec = f'{spec} {space_part}'

    # Step 2: 通用正则抽规格
    if not spec:
        extracted = []
        for pattern, _ in GENERIC_SPEC_PATTERNS:
            m = pattern.search(breed)
            if m:
                grp = m.group(0)
                if grp not in extracted:
                    extracted.append(grp)
                    breed = (breed[:m.start()] + breed[m.end():]).strip()
        if extracted:
            spec = ' '.join(extracted)
            breed = breed.strip()

    # Step 3: 领域特例 — 玻璃厚度 (5+12A+5mm / 5+9A+5mm)
    if not spec and '玻璃' in breed:
        m = re.search(r'((?:\d+\+)*\d+A?\+?\d+mm)$', breed)
        if m:
            spec = m.group(1)
            breed = breed[:m.start()].strip()

    # Step 4: 领域特例 — 混凝土标号+石料 (C30 碎石 / C20 卵石)
    if not spec and '混凝土' in breed:
        m = re.search(r'(C\d+(?:\.\d+)?)\s*(\S+)$', breed)
        if m:
            spec = f'{m.group(1)} {m.group(2)}'
            breed = breed[:m.start()].strip()

    # 拿不到任何 spec → 还原原值（不脏写）
    if not spec and not original_spec:
        return original_breed, original_spec
    if not spec and original_spec:
        # 原 spec 还在但 breed 被正则制过，还原 breed
        return original_breed, original_spec

    return breed, spec


def apply_smart_split(row: dict) -> dict:
    """对单条 ODS doc 应用智能拆分，返回 row（修改原 row）。"""
    if not isinstance(row, dict):
        return row
    breed = row.get('breed') or ''
    spec = row.get('spec') or ''
    new_breed, new_spec = smart_split_breed_spec(breed, spec)
    row['breed'] = new_breed
    row['spec'] = new_spec
    return row


# v0.3 (2026-07-26): 入 ODS 前的源端清洗
# 背景: ETL 的 v3 lookup 是 strict exact match, ODS 里如果含 \n/全角括号就会 miss。
# 治本: 在入 ODS 前先 normalize 掉脏字符 — ODS 形态 = v3 形态, ETL hit=100%。
def clean_for_ods(text: str) -> str:
    """入 ODS 前的脏字符清洗 — strip \\n/\\r/\\t, 全角→半角, 压空格。返回清洗后字符串。"""
    if not text:
        return text
    text = text.replace('\n', '').replace('\r', '').replace('\t', ' ')
    text = text.replace('（', '(').replace('）', ')')
    text = text.replace('【', '[').replace('】', ']')
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def pre_ods_clean(doc: dict) -> dict:
    """对整条 doc 应用入 ODS 前的清洗（处理所有字符串字段）。

    - breed, spec 等用户字段
    - 返回 doc（修改原 dict）
    - 如果清洗后 breed 为空，返回 None 让调用方 drop
    """
    if not isinstance(doc, dict):
        return doc
    for k in ('breed', 'spec', 'remark', 'category', 'section'):
        if k in doc and isinstance(doc[k], str):
            doc[k] = clean_for_ods(doc[k])
    # 清洗后 breed 为空 — 标记为不写入
    if not (doc.get('breed') or '').strip():
        return None
    return doc


def ensure_ods_index(es, host, index):
    """确保 ODS 索引存在，套用 mapping（如果不存在）

    v0.5 (2026-07-02) ：委托到 gov_price_etl.mappings.build_ods_mapping。
    v0.8 (2026-07-03) ：扩展 city_extension，加 vat_rate / region 字段。
    城市特化字段：section / price_kind / vat_rate / region
    """
    if es.indices.exists(index=index):
        return
    from gov_price_etl.mappings import build_ods_mapping
    mapping = build_ods_mapping(city_extension={
            "section":   {'type': 'text', 'fields': {'keyword': {'type': 'keyword', 'ignore_above': 256}}},
            "price_kind": {'type': 'keyword'},
            "vat_rate":  {'type': 'float'},  # 平均税率（PDF 直接给，huhehaote 用）
            "region":    {'type': 'keyword'},  # 旗县区（土默特左旗 / 托克托县 / ...）
        })
    es.indices.create(index=index, body=mapping)

def ensure_progress_index(es, index):
    """确保同步进度索引存在

    v0.6 (2026-07-02) ：委托到 gov_price_etl.mappings.build_progress_mapping。
    单点维护 36 个进度字段（含 2026-07-02 chongqing v3 加的 percent 等）。

    _id 规则（v0.6 标准化建议）：
        区县进度：f"{run_id}__{source}__{county}__{period}"
        run 汇总：f"{run_id}__summary"
        spot check：f"{run_id}__spot__{county}"
    """    
    if es.indices.exists(index=index):
        return
    from gov_price_etl.mappings import build_progress_mapping
    es.indices.create(index=index, body=build_progress_mapping())
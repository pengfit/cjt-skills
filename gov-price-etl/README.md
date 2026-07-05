# gov-price-etl

政府材料价格数据入仓 ETL 流水线（v0.6，2026-07）。

> 📘 详细 Skill 描述见 [SKILL.md](./SKILL.md)
> 📐 重构说明见 [SKILL.md#重构说明（v0.1-→-v0.6）](./SKILL.md)
> 📏 规格解析规则库见 [SPEC_RULES.md](./SPEC_RULES.md)

## 简介

将 17 个城市的 ODS 层原始数据（`ods_material_{city}_price`）清洗为结构化层（DWD）`dwd_{city}_price`，再聚合同步到展示层（DWS）`dws_{city}_price`。

**支持 17 城**：`xian` / `sichuan` / `chongqing` / `jinan` / `rizhao` / `henan` / `heze` / `qingdao` / `hainan` / `huhehaote` / `hunan` / `jiangxi` / `ningxia` / `qinghai` / `shaanxi` / `weihai` / `xinjiang`

## 快速开始

```bash
cd skills/gov-price-etl

# 全量 ETL（17 个城市，ODS → DWD → DWS）
./cli/etl.py

# 只处理一个城市
./cli/etl.py --city sichuan

# 增量模式（按 update_date）
./cli/etl.py --incremental --since 2026-05-01

# 只清洗指定分类
./cli/etl.py --category 瓦

# 预览（不写入 ES）
./cli/etl.py --dry-run

# 只跑 ETL（跳过 DWS 同步）
./cli/etl.py --no-dws

# 独立 DWS 同步（quick 模式，跳过 AI）
./cli/sync_dws.py --city xian

# AI 补全 DWS（缺 attr 走 AI 三段式）
./cli/sync_dws.py --mode ai --city xian

# 重读 prompts.yml（修改 AI 提示词后无需重启 ETL）
./cli/reload_prompts.py
```

## 三段式架构

### ODS → DWD（品种分类 + 清洗）

```
阶段 1: breed_category_rules.db 精确查表           → category_source='db_exact' / category_stage='1'
阶段 2: DB + Jaccard 模糊召回（阈值 0.45）          → category_source='db_fuzzy' / category_stage='2'
阶段 3: AI 攒批分类（20 条/批串行调 Dify workflow） → category_source='ai' / 'ai_fallback' / category_stage='3'
```

### DWD → DWS（规格解析 + 聚合）

```
阶段 1: DWD attr 非空 → 直接同步                   → attr_source='etl'
阶段 2: 本地 breed_spec_rules.db 向量规则库解析     → attr_source='local_db'
阶段 3: AI batch_spec_parse 串行解析（20 条/批）    → attr_source='ai' / 'ai_fallback'
```

## 目录结构

```
gov-price-etl/
├── SKILL.md
├── README.md                    # 本文件
├── SPEC_RULES.md                # parse_spec 规则库使用说明
├── config.yml                   # ES 连接配置
├── prompts.yml                  # AI Prompt 模板（fix_case / classify_breed_batch / batch_spec_parse）
│
├── data/                        # 数据文件集中
│   ├── breed_spec_rules.db      # 规格解析规则（SQLite 向量规则库）
│   ├── breed_category_rules.db  # 品种分类规则（v3 GB 章节体系）
│   ├── category_in_system.json  # 分类体系映射
│   └── ai_cache.db              # AI 调用缓存（gitignored）
│
├── gov_price_etl/               # 核心包（每个模块 < 250 行）
│   ├── paths.py                 # 路径中心（零硬编码绝对路径）
│   ├── config.py                # 配置 + CITY_CONFIGS（17 城注册）
│   ├── es_client.py             # ES 客户端 + bulk
│   ├── mappings.py              # DWD / DWS mappings（含 period_* 字段）
│   ├── indexer.py               # 索引模板 / ensure_indices
│   ├── transform/
│   │   ├── clean.py             # 品种/规格/单位/价格清洗
│   │   ├── doc.py               # transform_doc ODS→DWD（不含 AI）
│   │   └── attr_utils.py        # attr 字段提取/转换
│   ├── parse_spec/              # 规格解析引擎（37+ 字段）
│   │   ├── __init__.py          # get_parser() 入口
│   │   ├── base.py              # BaseParseSpec 基类
│   │   ├── xian.py / sichuan.py / henan.py
│   │   └── rules/
│   │       ├── _attrs.py
│   │       └── vector_store.py  # SQLite 向量规则库
│   ├── classify/                # 品种分类引擎（v3 4 层）
│   │   ├── __init__.py          # classify_breed_db_exact/db_fuzzy/ai
│   │   ├── system.py            # v3 分类体系（GB 50854/50856/50857/50858）
│   │   └── rules/
│   │       ├── _core.py         # 阶段 1+2+3 主体
│   │       └── jaccard.py       # Jaccard 召回引擎
│   ├── ai/                      # AI 服务
│   │   ├── service.py           # parse_spec_batch / classify_breed_batch（20 条/批串行）
│   │   ├── prompts.py           # Prompt 加载（外部 yml）
│   │   └── cache.py             # SQLite 缓存
│   ├── pipeline/
│   │   ├── etl.py               # ODS→DWD 三段式主流程
│   │   └── dws_sync.py          # DWD→DWS 三段式主流程
│   └── collectors/              # 采集器抽象基类（v0.8+，供各 city skill 复用）
│       ├── base.py              # SignalHandler / LocalProgressStore / SyncRunner (ABC)
│       └── client.py            # ES / MinIO / HTTP 工具
│
└── cli/                         # 入口脚本
    ├── etl.py                   # ODS → DWD → DWS 主入口
    ├── sync_dws.py              # DWD → DWS 独立同步（--mode quick|plain|ai）
    └── reload_prompts.py        # 重读 prompts.yml（无需重启 ETL）
```

## 采集器抽象基类（v0.8+）

各城市 sync.py 在采集端逻辑高度相似：**多周期 × 多 source × 断点续传 × SIGINT × 进度上报**。v0.8 起提供 `gov_price_etl.collectors` 抽取通用基础设施，供城市复用。

### 设计原则

- **接口稳定，不强迁**——子类重写钩子函数，不必继承 SyncRunner（duck typing）
- **只抽通用基础设施**（SIGINT / 本地进度 / 进度上报），站点特化逻辑（chongqing browser / qingdao PDF / sichuan ASP.NET / xinjiang xlsx）占各 sync.py 80% 代码，**不强行抽象**
- **可测试**——每个组件可独立 mock
- **渐进接入**——chongqing 作为首个试点，其他城市按需接入，不强制

### 三个组件

| 组件 | 职责 | 使用场景 |
|---|---|---|
| **`SignalHandler`** | SIGINT 中断上下文管理器 | sync 主循环响应 Ctrl+C |
| **`LocalProgressStore`** | 本地 JSON 进度存储 | 断点续传（key 形状灵活）|
| **`SyncRunner(ABC)`** | 主流程基类 | 城市继承，重写 4 个钩子 |

### SyncRunner 钩子

| 钩子 | 默认 | 用途 |
|---|---|---|
| `_list_work_units()` | abstract | 扁平化所有工作单元（如 `(source, county, period)` 三元组）|
| `_process_one(unit)` | abstract | 处理单个单元：抓 + 解析 + 写 ES |
| `_on_unit_start(unit)` | print | 单元开始钩子 |
| `_on_unit_done(unit, n, status)` | print | 单元完成钩子 |
| `_compute_unit_key(unit)` | str(unit) | 本地进度 key |

### 已接入城市

- **chongqing**（v0.8 试点，v0.9 默认路径）—— `chongqing_collector.py` 用 SyncRunner 重构原 cmd_sync 主流程
- **henan / heze / huhehaote / hunan / jiangxi / ningxia / qingdao / qinghai / shaanxi / xinjiang** —— v0.8+ 各 PDF 采集 skill 用 SyncRunner 化
- **xian / jinan / rizhao / sichuan / weihai** —— 沿用原 sync.py（HTML/ASP.NET/SPA），未强制改造

## v3 分类体系（4 层 64 节点）

按 GB 50854-2013 / GB/T 50856-2024 / GB 50857-2013 / GB 50858-2013 重建：

- **8 L1 专业大类**：建筑工程 / 装饰装修 / 安装工程 / 市政工程 / 园林景观 / 水利工程 / 公路工程 / 其他
- **42 L2 分部工程**
- **145 L3 分项工程**
- **4 层联合主键**：L1 + L2 + L3 + L4

数据源：`data/breed_category_rules.db`（SQLite）+ `data/category_in_system.json`（体系映射）。

v1 大类字典（28 类）+ v2 4 层 64 节点已于 2026-06 废止。

## AI 集成（2026-06-18 起）

- 统一走 **Dify workflow API**（替代 OpenClaw gateway）
- 严格**串行**：默认 20 条/批，逐批调用，批间 sleep 0.5s 限速
- 缓存：`data/ai_cache.db`（SQLite，避免重复调用）
- 失败兜底：`ai_fallback` 标记

Prompt 模板从 `gov-price-etl/prompts.yml` 加载（不是 hard-coded），修改后 `./cli/reload_prompts.py` 即可生效，无需重启 ETL。

## 重构历史

| 版本 | 日期 | 重点 |
|---|---|---|
| **v0.1** | 2026-04 | 单文件 1107 行上帝模块 `etl.py` |
| **v0.2** | 2026-05 | 拆分为 `gov_price_etl` 包（7 个模块，每个 < 250 行）；拍平 src/ 层级；DWS sync 三合一（quick/plain/ai） |
| **v0.3** | 2026-06 初 | ODS→DWD 引入 v1 显式三段式，DWD→DWS 保持三段式 |
| **v0.4** | 2026-06-17 | v1 大类字典废，分类重写为 v2 4 层 64 节点；DWD 走"先 DB 后 AI"两轮 |
| **v0.5** | 2026-06-18 | AI 切到 Dify workflow API；prompts.yml 外部化；mappings 集中维护 |
| **v0.6** | 2026-06-19 | v2 → v3 4 层体系（GB 章节重建）；分类 → 5 段式（breed_l3_map 精确 / Jaccard 模糊 / L4 pattern / unit 兜底 / AI 攒批）；collectors 抽象基类 v0.8+ |

## 配置（config.yml）

```yaml
es:
  host: http://localhost:59200
  batch_size: 500

sync:
  last_update_date: ""
```

## 相关

- [gov-price-etl/SKILL.md](./SKILL.md) — 详细接口契约
- [SPEC_RULES.md](./SPEC_RULES.md) — parse_spec 规则库使用说明
- [gov-price-dashboard/](../gov-price-dashboard/) — 看板（消费 DWS 数据）
- 各城市采集 skill：`../{xian,sichuan,chongqing,...}-price/`
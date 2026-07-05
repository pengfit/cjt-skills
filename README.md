# cjt-skills

政府材料价格数据流水线技能集合，覆盖 17 个省/市的数据采集、ETL 清洗、数据可视化全链路。

## 架构

```
原始数据源 (17 个政府工程造价网站)
    ↓
[城市]-price (数据同步 → ods_material_{city}_price)
    ↓
gov-price-etl (ETL 清洗)
    ↓
dwd_{city}_price (清洗层 + 品种分类 + 规格解析)
    ↓
gov-price-etl/commands/sync_dws (聚合同步)
    ↓
dws_{city}_price (聚合层)
    ↓
gov-price-dashboard (可视化)
```

## 目录结构

```
cjt-skills/
├── gov-price-etl/              # ETL 公共层（v0.6）
│   ├── cli/                    # CLI 入口（etl.py / sync_dws.py / reload_prompts.py）
│   ├── gov_price_etl/          # 核心包
│   │   ├── transform/          # ODS→DWD 数据清洗
│   │   ├── parse_spec/         # 规格解析引擎（37+ 字段，SQLite 向量规则库）
│   │   ├── classify/           # 品种分类（v3 4 层：8 L1 / 42 L2 / 145 L3）
│   │   ├── ai/                 # AI 服务（Dify workflow，串行 20 条/批）
│   │   ├── pipeline/           # ETL 主流程
│   │   │   ├── etl.py          # ODS→DWD 三段式（DB 5 段式 + AI 攒批）
│   │   │   └── dws_sync.py     # DWD→DWS 三段式（attr / 本地规则库 / AI）
│   │   └── collectors/         # 采集器抽象基类（v0.8+）
│   │       ├── base.py         # SignalHandler / LocalProgressStore / SyncRunner
│   │       └── client.py       # ES / MinIO / HTTP 工具
│   ├── data/                   # SQLite 规则库（breed_spec_rules / breed_category_rules）
│   ├── prompts.yml             # AI Prompt 模板
│   ├── SPEC_RULES.md           # parse_spec 规则库使用说明
│   └── config.yml
│
├── gov-price-dashboard/         # 数据可视化看板（材价通）
│   ├── api/                    # FastAPI 后端 :5200
│   │   ├── main.py             # 搜索/统计/同步进度接口
│   │   ├── skill_registry.py   # Skill 自动注册（扫盘 skill.yml）
│   │   └── routes/
│   └── frontend/               # Vue3 前端 :5300
│       └── src/components/     # 50+ Vue 组件
│
├── chongqing-price/            # 重庆（county 模式，35 区县，3 source + v4 区间价）
├── hainan-price/               # 海南（period 模式，PDF + MinIO，2026 年仅 4 期）
├── henan-price/                # 河南（period 模式，18 地市，PDF 双月合刊）
├── heze-price/                 # 菏泽（period 模式，期刊 + PDF）
├── huhehaote-price/            # 呼和浩特（period 模式，双月刊 + PDF）
├── hunan-price/                # 湖南（period 模式，14 页 2 类期刊）
├── jiangxi-price/              # 江西（period 模式，articleList JSON + PDF）
├── jinan-price/                # 济南（catalogue 模式，41 分类目录 + Playwright token）
├── ningxia-price/              # 宁夏（period 模式，双月刊 + PDF）
├── qingdao-price/              # 青岛（period 模式，月度 PDF）
├── qinghai-price/              # 青海（period 模式，双月合刊大 PDF，95-275MB）
├── rizhao-price/               # 日照（catalogue 模式，3 类别，Playwright + REST API）
├── shaanxi-price/              # 陕西（period 模式，省本级 + 9 设区市，7 种 PDF 格式）
├── sichuan-price/              # 四川（catalogue 模式，21 地市/自治州）
├── weihai-price/               # 威海（period 模式，季度 + dataproxy jpage 插件）
├── xian-price/                 # 西安（county 模式，6 区县，按造价信息表月份）
├── xinjiang-price/             # 新疆（county 模式，16 地州 + xlsx 多 sheet）
│
├── self-improving-agent/       # 自改进 Agent 技能（OpenClaw 平台）
├── scripts/                    # 工具脚本
│   ├── gen_skill_docs.py       # SKILL.md / README.md 批量生成器
│   ├── fix_hardcoded_paths.py  # ETL 路径硬编码批量替换
│   └── update_resolver.py      # 解析器更新工具
└── README.md
```

## 快速启动

### 数据同步（以西安为例）

```bash
cd skills/xian-price

./run.sh preview          # 预览数据（不写入 ES）
./run.sh sync             # 增量同步（自动断点续传）
./run.sh sync --force     # 强制全量同步
./run.sh status           # 查看同步状态
./run.sh check            # 增量检测
./run.sh test             # 测试 ES / 源站连通性
```

### ETL 清洗（全城市）

```bash
cd skills/gov-price-etl

# 全量 ETL（17 个城市）
./cli/etl.py

# 只处理指定城市
./cli/etl.py --city xian

# 增量模式（按 update_date）
./cli/etl.py --incremental --since 2026-05-01

# 独立 DWS 同步（quick / plain / ai 三种模式）
./cli/sync_dws.py --city xian --mode quick
./cli/sync_dws.py --city xian --mode ai
```

### 数据看板

```bash
cd skills/gov-price-dashboard

./start.sh                # 启动
./start.sh status         # 查看状态
./start.sh stop           # 停止
./start.sh restart        # 重启
```

- 前端：http://localhost:5300
- API：http://localhost:5200
- API 文档：http://localhost:5200/docs

## 数据层说明

| 层次 | 说明 | 示例索引 |
|------|------|---------|
| **ODS** | 原始抓取数据，未清洗 | `ods_material_xian_price` |
| **DWD** | 清洗数据，含 attr 结构化字段 + 分类 | `dwd_xian_price` |
| **DWS** | 聚合数据，API 查询层 | `dws_xian_price` |

### ODS → DWD 三段式

```
阶段 1: breed_category_rules.db 精确查表     → category_source='db_exact'
阶段 2: DB + Jaccard 模糊召回（阈值 0.45）   → category_source='db_fuzzy'
阶段 3: AI 攒批分类（20 条/批串行调 Dify）   → category_source='ai' / 'ai_fallback'
```

### DWD → DWS 三段式

```
阶段 1: DWD attr 非空 → 直接同步              → attr_source='etl'
阶段 2: 本地 breed_spec_rules.db 解析         → attr_source='local_db'
阶段 3: AI batch_spec_parse 串行解析          → attr_source='ai' / 'ai_fallback'
```

## attr 解析字段（37+ 种）

`parse_spec` 把复合规格解析为结构化字段：

| 分类 | 字段 |
|------|------|
| **尺寸** | `thickness` `length` `width` `height` `height_range` `diameter` `inner_diameter` `wall_thickness` `length_range` |
| **电缆** | `cross_section` `cores` `voltage` `current` `fiber_core` `cable_length` |
| **材质** | `material` `color` `grade` `surface` |
| **专业** | `asphalt_type` `cement_content` `channels` `doors` `fire_rating` `ip_rating` |
| **洁具** | `drain_type` `installation_type` `inlet_type` |
| **其他** | `temperature` `temp_range` `humidity_range` `pressure` `ring_stiffness` `media` `range` `output` |

## 17 个城市采集 skill

| 城市 | province | progress_mode | 数据源类型 | 周期窗口 | ODS 索引 |
|------|----------|---------------|-----------|---------|---------|
| [xian](./xian-price/) | 陕西 | county | HTML 6 区县 | 按造价信息表月份 | `ods_material_xian_price` |
| [sichuan](./sichuan-price/) | 四川 | catalogue | ASP.NET 21 地市 | 按月周期 | `ods_material_sichuan_price` |
| [chongqing](./chongqing-price/) | 重庆 | county | Browser 35 区县 + 3 source | 按月份 | `ods_material_chongqing_price` |
| [jinan](./jinan-price/) | 山东 | catalogue | Playwright + REST API 41 目录 | 按周期 | `ods_material_jinan_price` |
| [rizhao](./rizhao-price/) | 山东 | catalogue | Playwright + REST 3 tab | 按月份 | `ods_material_rizhao_price` |
| [heze](./heze-price/) | 山东 | period | API + HTML + PDF | 按期刊期数 | `ods_material_heze_price` |
| [henan](./henan-price/) | 河南 | period | HTML 4 页 + PDF | 按期刊期数 | `ods_material_henan_price` |
| [qingdao](./qingdao-price/) | 山东 | period | HTML + PDF | 月度 | `ods_material_qingdao_price` |
| [hainan](./hainan-price/) | 海南 | period | HTML 10 页 + PDF | 月度 | `ods_material_hainan_price` |
| [huhehaote](./huhehaote-price/) | 内蒙古 | period | HTML + PDF | 双月刊 | `ods_material_huhehaote_price` |
| [hunan](./hunan-price/) | 湖南 | period | HTML 14 页 + PDF（2 类）| 按期刊 | `ods_material_hunan_price` |
| [jiangxi](./jiangxi-price/) | 江西 | period | HTML articleList JSON + PDF | 按期刊 | `ods_material_jiangxi_price` |
| [ningxia](./ningxia-price/) | 宁夏 | period | HTML 5 页 + PDF | 双月刊 | `ods_material_ningxia_price` |
| [qinghai](./qinghai-price/) | 青海 | period | HTML 4 页 + PDF | 双月合刊 | `ods_material_qinghai_price` |
| [shaanxi](./shaanxi-price/) | 陕西 | period | HTML 5 页 + 7 种 PDF 格式 | 月/双月/季 | `ods_material_shaanxi_price` |
| [weihai](./weihai-price/) | 山东 | period | jpage dataproxy + PDF | 季度 | `ods_material_weihai_price` |
| [xinjiang](./xinjiang-price/) | 新疆 | county | HTML + xlsx 多 sheet | 月度 | `ods_material_xinjiang_price` |

> 各 skill 通过 `skill.yml` 自动注册到 dashboard，启动时扫盘加载。
> 新增 skill：加 `skill.yml` → `curl -X POST http://localhost:5200/api/skill-registry/reload`

## 公共层依赖（采集器抽象基类 v0.8+）

各采集 skill 通过继承 `gov_price_etl.collectors.SyncRunner` 复用：

- **SignalHandler**：SIGINT 中断上下文（Ctrl+C 安全）
- **LocalProgressStore**：本地 JSON 进度存储（断点续传）
- **SyncRunner (ABC)**：主流程基类，4 个钩子：
  - `_list_work_units()`：扁平化工作单元
  - `_process_one(unit)`：处理单单元（抓 + 解析 + 写 ES）
  - `_on_unit_done(unit, n, status)`：完成钩子
  - `_compute_unit_key(unit)`：进度 key

设计原则：**接口稳定不强迁**——各 skill 可独立接入，不必改造现有 sync.py。

## 字段约定（v0.8+）

每个 ODS 文档必含字段：

| 字段 | 类型 | 来源 |
|------|------|------|
| `period` | keyword | 业务期号（如 `2026.5月` / `2026.第1期` / `2026-05`） |
| `period_start` | date | 周期起始日（`YYYY-MM-DD`） |
| `period_end` | date | 周期结束日 |
| `period_days` | integer | 周期天数 |
| `province` | keyword | 省份 |
| `city` | keyword | 地市 |
| `county` | keyword | 区县（county 模式有值） |

`period_start/end/days` 由各 skill 的 `parse_period_window()` 推算（PDF 双月刊按 N 期映射 2 个月，单月按当月窗口）。

## 环境依赖

| 组件 | 依赖 |
|------|------|
| 各城市采集 skill | Python 3.10+, requests, beautifulsoup4, pyyaml, elasticsearch |
| PDF 类 skill（henan/hainan/qingdao/...）| + pdfplumber, boto3 (MinIO) |
| Playwright 类 skill（jinan/rizhao）| + playwright + chromium |
| Browser 类 skill（chongqing）| openclaw browser |
| gov-price-etl | + curl（SSL renegotiation 兜底）|
| gov-price-dashboard | FastAPI, Vue3, ECharts 6.x |

## 相关文档

| Skill | 说明 |
|-------|------|
| [gov-price-etl/SKILL.md](./gov-price-etl/SKILL.md) | ETL 公共层（ODS→DWD→DWS 三段式） |
| [gov-price-etl/README.md](./gov-price-etl/README.md) | ETL 使用与运维文档 |
| [gov-price-etl/SPEC_RULES.md](./gov-price-etl/SPEC_RULES.md) | parse_spec 规则库使用说明 |
| [gov-price-dashboard/SKILL.md](./gov-price-dashboard/SKILL.md) | 数据看板 API + 前端 |
| [gov-price-dashboard/README.md](./gov-price-dashboard/README.md) | 看板使用与新增 skill 接入 |
| [self-improving-agent/SKILL.md](./self-improving-agent/SKILL.md) | 自改进 Agent 技能 |
| [scripts/gen_skill_docs.py](./scripts/gen_skill_docs.py) | SKILL.md / README.md 批量生成器 |
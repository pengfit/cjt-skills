# cjt-skills

政府材料价格数据流水线技能集合，覆盖 17 个省/市的数据采集、ETL 清洗、标准化、可视化全链路。

## 架构总览

```
原始数据源 (17 个政府工程造价网站)
    ↓
[城市]-price (同步 → ods_material_{city}_price)
    ↓
gov-price-etl (清洗 → dwd_{city}_price)
    ↓
gov-price-etl/sync_dws (聚合同步 → dws_{city}_price)
    ↓
gov-price-normalization (标准化 → norm_{city}_price)  ← Dashboard 默认数据源
    ↓
gov-price-dashboard (可视化 · /home /market)
```

## attr 脏数据治本闭环（2026-07-22 · 32.66% → 0%）

三段式架构，按"净化上游 → 封堵中游 → 修正下游"分层（详见 [`gov-price-normalization/SKILL.md`](./gov-price-normalization/SKILL.md) L1 fields）：

| 层 | 实现位置 | 关键作用 |
|---|---|---|
| **L1 NORM 净化**（治本核心）| `gov-price-normalization/layers/fields.py::sanitize_attr()` | 删 9 大脏模式（volume/package_type/cross_section_area/height_min/thickness_min/mix_grade/particle_size/brand=DN/价格）+ L3 类目白名单（`category_attr_whitelist.json`）+ HARD_REJECT 护栏 |
| **L2 ETL 封堵**（治标）| `gov-price-etl/transform/attr_utils.py` + `parse_spec/base.py` | volume/brand 黑名单 + material 描述词拒 + `_CATCH_ALL_FORBIDDEN_KEYS` + `parse_spec/cable.py`（GB/T 12706 电缆命名）|
| **L3 类目修正** | `breed_canonical.db` | 295 条 PVC-U/PPR/PE/PP 排水管错分类（瓦/砌块→管材）|

**关键不变量**：L1 先于 L2/L3 跑（attr 净化是上游），数据驱动 + 分层防护（L1 净化兜底 + L2 类目规则 + HARD_REJECT 护栏）。

## 4 个框架模块

### [gov-price-etl](./gov-price-etl/) — ETL 公共层（v0.7）

- **ODS→DWD 三段式**：DB 5 段式（精确查表 → Jaccard 模糊 → 单元兜底 → L4 pattern）+ AI 攒批（未命中调 Dify workflow）
- **DWD→DWS 三段式**：attr 非空直同步 → 本地 `breed_spec_rules.db` → AI 串行解析
- **v3 GB 章节 4 层分类**：8 L1 / 42 L2 / 145 L3（GB 50854-2013 / GB/T 50856-2024 / GB 50857-2013 / GB 50858-2013）
- **采集器抽象基类**：`SyncRunner` / `SignalHandler` / `LocalProgressStore`（v0.8+，各城市 sync.py 可继承复用）
- 详见 [gov-price-etl/SKILL.md](./gov-price-etl/SKILL.md)

### [gov-price-normalization](./gov-price-normalization/) — 标准化层（v0.2）

- **4 层独立纯函数**，与 ETL 解耦：
  - **L1 fields** — `sanitize_attr()` 删脏/修错位 + `normalize_cable_type()` 电缆重拆
  - **L2 units** — 单位换算（按 L3 default_unit 归一价格）
  - **L3 periods** — 业务期对齐（monthly/quarterly/bimonthly/irregular）
  - **L4 cross_city** — 跨城品种映射（占位）
- **NORM 索引** `norm_{city}_price`，Dashboard 默认查 NORM，缺失时降级 DWS
- 详见 [gov-price-normalization/SKILL.md](./gov-price-normalization/SKILL.md)

### [gov-price-dashboard](./gov-price-dashboard/) — 材价通看板

- FastAPI :5200 + Vue3 :5300 + ECharts 6.x
- **公开页**：`/home`（landing，pengfit-redesign 深色赛博朋克风）+ `/market`（市场行情，跨城归一）
- **鉴权**：单 admin JWT，`/api/*` 全部强制 Bearer（`/api/auth/login` 除外）
- **声明式 skill 注册**：`skill.yml` 自动扫盘 → `ALL_INDICES` + sync-progress 端点
- **数据源优先级**：NORM > DWS（缺失自动降级）
- 详见 [gov-price-dashboard/SKILL.md](./gov-price-dashboard/SKILL.md)

### 17 个城市采集 skill

各 skill 通过 `skill.yml` 自动注册到 Dashboard，**结构相似但 progress_mode 不同**：

| progress_mode | 城市 | 抓取维度 |
|---|---|---|
| **county**（按区县）| 西安 / 重庆 / 新疆 | 35 区县 |
| **period**（按期期刊）| 海南 / 河南 / 菏泽 / 呼和浩特 / 湖南 / 江西 / 宁夏 / 青岛 / 青海 / 陕西 / 威海 | 6-18 期 |
| **catalogue**（按分类目录）| 济南 / 日照 / 四川 | 3-41 目录 |

详见各 `*-price/SKILL.md` 或 Dashboard 的「数据同步」页（`http://localhost:5300/sync`）。

## 数据层

| 层次 | 模块 | 索引示例 | 关键字段 |
|------|------|---------|---------|
| **ODS** | 城市采集 | `ods_material_xian_price` | 原始字段 + `period_start/end/days` + `province/city/county` |
| **DWD** | ETL 清洗 | `dwd_xian_price` | + `category_v2_source`（`db_exact_v3`/`db_fuzzy_v3`/`ai`/`ai_fallback`）+ `attr`（nested）|
| **DWS** | ETL 聚合 | `dws_xian_price` | + `attr_source`（`etl`/`local_db`/`ai`/`ai_fallback`）+ `normalized_breed` |
| **NORM** | NORM 标准化 | `norm_xian_price` | + `period_norm` / `unit_norm` / `price_norm` / `attr_norm` / `_norm.status` |

## 快速启动

```bash
# 1. 启动看板
cd skills/gov-price-dashboard && ./start.sh
# 前端：http://localhost:5300  ·  API：http://localhost:5200  ·  文档：http://localhost:5200/docs

# 2. 单城同步（如西安）
cd skills/xian-price && ./run.sh sync

# 3. 全量 ETL（三段式，AI 攒批）
cd skills/gov-price-etl && ./cli/etl.py
./cli/etl.py --city xian          # 单城市
./cli/etl.py --incremental --since 2026-05-01   # 增量

# 4. 独立 DWS 同步（quick/plain/ai 三种模式）
./cli/sync_dws.py --city xian --mode quick   # 只同步已有 attr
./cli/sync_dws.py --city xian --mode ai      # 缺 attr 走规则库 + AI

# 5. 一键部署（本地构建 + 容器重启）
cd skills/gov-price-dashboard && ./deploy.sh build && ./deploy.sh deploy
```

## 相关文档

| 文档 | 内容 |
|------|------|
| [gov-price-etl/SKILL.md](./gov-price-etl/SKILL.md) | ETL 三段式 + attr 治本 L2 封堵 + v3 分类 |
| [gov-price-normalization/SKILL.md](./gov-price-normalization/SKILL.md) | 4 层标准化 + attr 治本 L1 净化（治本核心） |
| [gov-price-dashboard/SKILL.md](./gov-price-dashboard/SKILL.md) | 看板架构 + /home /market / JWT / skill.yml |
| [gov-price-etl/SPEC_RULES.md](./gov-price-etl/SPEC_RULES.md) | parse_spec 规则库使用说明 |
| [scripts/gen_skill_docs.py](./scripts/gen_skill_docs.py) | SKILL.md / README.md 批量生成器 |
| [self-improving-agent/SKILL.md](./self-improving-agent/SKILL.md) | 自改进 Agent 技能 |
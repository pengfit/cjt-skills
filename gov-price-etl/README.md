# gov-price-etl

政府材料价格数据入仓 ETL 流水线。

> 📘 详细 Skill 描述见 [SKILL.md](./SKILL.md)
> 📐 重构说明见 [SKILL.md#重构说明（v0.1-→-v0.2）](./SKILL.md#重构说明v01--v02)

## 简介

将各城市 ODS 层原始数据（`ods_material_{city}_price`）清洗为结构化层（DWD）`dwd_{city}_price`，再聚合同步到展示层（DWS）`dws_{city}_price`。

支持城市：`xian` / `sichuan` / `chongqing` / `jinan` / `rizhao` / `henan` / `heze`

## 快速开始

```bash
cd skills/gov-price-etl

# 全量 ETL（所有城市）
./cli/etl.py

# 只处理一个城市
./cli/etl.py --city sichuan

# 增量模式（按 update_date）
./cli/etl.py --incremental --since 2026-05-01

# 预览（不写入 ES）
./cli/etl.py --dry-run

# 独立 DWS 同步（quick 模式，跳过 AI）
./cli/sync_dws.py --city xian

# AI 补全 DWS（缺 attr 的走 AI）
./cli/sync_dws.py --mode ai --city xian
```

## 目录结构

```
gov-price-etl/
├── SKILL.md                  # Skill 详细描述
├── README.md                 # 本文件
├── SPEC_RULES.md             # parse_spec 规则库使用说明
├── config.yml                # ES 连接配置
├── data/                     # 数据文件
│   ├── breed_spec_rules.db
│   ├── breed_category_rules.db
│   └── category_in_system.json
├── gov_price_etl/        # 核心包
│   ├── paths.py              # 路径中心
│   ├── config.py             # 配置 + 城市注册
│   ├── es_client.py          # ES 客户端
│   ├── mappings.py           # DWD/DWS mappings
│   ├── indexer.py            # 索引创建
│   ├── transform/            # 数据清洗
│   ├── parse_spec/           # 规格解析
│   ├── classify/             # 品种分类
│   ├── ai/                   # AI 服务
│   └── pipeline/             # ETL 主流程
├── cli/                      # 入口脚本
│   ├── etl.py
│   └── sync_dws.py
```

## v0.2 重构亮点

- **拆掉 1107 行的上帝模块** → 7 个独立模块，每个 < 250 行
- **三合一 DWS 同步** → `cli/sync_dws.py --mode {quick,plain,ai}`
- **零 `sys.path` 黑魔法** → 拍平布局 + `paths.py` 中心化
- **零硬编码绝对路径** → `paths.py` 解析所有 DB/JSON

详细对照见 [SKILL.md 重构说明](./SKILL.md#重构说明v01--v02)。

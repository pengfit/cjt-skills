---
name: xinjiang-price
description: "新疆工程造价材料信息采集,从 `https://www.xjzj.com` 抓取数据,按区县跟踪,同步至 Elasticsearch。覆盖 16 个区县。"
---

# 新疆 · 工程造价材料信息采集

> 省份:新疆 · 进度模式:`county` · 范围(16): 伊犁, 乌鲁木齐, 昌吉, 克拉玛依, 石河子, 塔城, 阿勒泰, 哈密, 巴州, 阿克苏, 喀什, 五家渠市, 博州, 克州, 和田地区, 吐鲁番

## 数据流

```
源站: https://www.xjzj.com
   ↓ (commands/sync.py)
ods_material_xinjiang_price
   ↓ ([gov-price-etl](../../gov-price-etl/) cli/etl.py --city xinjiang)
dwd_xinjiang_price
   ↓ (cli/sync_dws.py --city xinjiang --mode quick)
dws_xinjiang_price
   ↓ ([gov-price-normalization](../../gov-price-normalization/) · Normalizer worker)
norm_xinjiang_price                          ← Dashboard 默认查 NORM，DWS 作 fallback
```

下游框架:
- ETL 三段式清洗 + attr 治本 L2 封堵 — [gov-price-etl](../../gov-price-etl/)
- NORM 标准化 + attr 治本 L1 净化 — [gov-price-normalization](../../gov-price-normalization/)
- 可视化(默认查 NORM) — [gov-price-dashboard](../../gov-price-dashboard/)

## 快速开始

```bash
cd <skills>/xinjiang-price
./run.sh preview          # 预览数据(不写 ES)
./run.sh sync             # 增量同步(自动断点续传)
./run.sh sync --force     # 强制全量同步
./run.sh status           # 查看同步状态
./run.sh check            # 增量检测
./run.sh test             # 测试 ES / 源站连通性
```

## 命令清单

| 命令 | 脚本 | 说明 |
|------|------|------|
| `sync` | commands/sync.py | 同步到 ES |
| `status` | commands/status.py | 查看状态 |
| `test` | commands/test.py | 测试连通性 |
| `check` | commands/check.py | 增量检测 |

## sync 关键参数

- `--year` — 目标年份
- `--areaid` — 只同步指定 areaid（0=全部）
- `--reset` — 重置进度
- `--dry-run` — 只下载 + 解析，不入库
- `--no-skip` — 不跳过已完成的条目

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_xinjiang_price` | 原始抓取数据(主数据) |
| `ods_material_xinjiang_price_sync_progress` | 同步进度(按 run_id 分组) |
| `dwd_xinjiang_price` | ETL 清洗层 |
| `dws_xinjiang_price` | 看板查询层 |

## 配置(config.yml)

```yaml
es:
  host: http://localhost:59200
  index: ods_material_xinjiang_price
  progress_index: ods_material_xinjiang_price_sync_progress
site:
  base_url: https://www.xjzj.com
  counties/tabs:
  - 伊犁
  - 乌鲁木齐
  - 昌吉
  - 克拉玛依
  - 石河子
  - 塔城
  - 阿勒泰
  - 哈密
  - 巴州
  - 阿克苏
  - 喀什
  - 五家渠市
  - 博州
  - 克州
  - 和田地区
  - 吐鲁番
sync:
  year: 2026
  last_period: 
```

## 项目结构

```
xinjiang-price/
├── run.sh
├── config.yml
└── commands/
    ├── check.py
    ├── fetch.py
    ├── parse.py
    ├── rebuild_split.py
    ├── repair_progress.py
    ├── status.py
    ├── sync.py
    ├── test.py
    ├── utils.py
```

## 依赖

- Python 3
- requests / beautifulsoup4 / pyyaml / elasticsearch

## 相关

- <skills>/gov-price-dashboard — 看板(查 DWS 数据)
- <skills>/gov-price-etl — ETL 公共层

---
name: jinan-price
description: "济南工程造价材料信息采集：从 jnxxj.jngczjxh.com:5020 抓取材料价格数据。"
---

# jinan-price

济南工程造价材料信息采集。从 `jnxxj.jngczjxh.com:5020` 抓取材料价格数据，支持多分类、多周期、断点续传、增量自动检测。

## 数据源

**URL**: `http://jnxxj.jngczjxh.com:5020`

**认证方式**: 使用 Playwright (Chromium) 启动无头浏览器访问网站，从 `localStorage` 读取 `token` 作为请求认证头。

**API 端点**（均为 `POST /cj/api/build/material/searchPublishPriceMaterialPage`，JSON body）：

| 用途 | 端点 |
|------|------|
| 搜索材料价格 | `POST /cj/api/build/material/searchPublishPriceMaterialPage` |
| 获取最新周期 ID | `GET /cj/api/build/period/getLastPeriodId` |
| 获取周期名称 | `GET /cj/api/build/period/selectPeriodList?periodId=ID` |
| 获取分类目录树 | `GET /cj/api/build/catalogue/catalogueTree?dataType=TYPE` |

**dataType**: 默认 `2`（信息价材料）

## 命令

| 命令 | 说明 |
|------|------|
| `./run.sh sync` | 增量同步（检测到新周期或分类增量时触发全量，写入 ES） |
| `./run.sh sync --force` | 强制全量同步，忽略增量检测 |
| `./run.sh sync --dry-run` | 预览模式，不写入 ES |
| `./run.sh sync --reset` | 重置本地进度，重新开始 |
| `./run.sh sync --period-id ID` | 指定周期 ID 同步 |
| `./run.sh preview` | 预览数据（默认前 10 个分类，前 2 页） |
| `./run.sh preview --pages N` | 指定预览页数 |
| `./run.sh status` | 查看同步进度（ES 计数、周期、本地进度、ES 进度记录） |
| `./run.sh test` | 测试 ES 和网站连接 |
| `python3 commands/check.py` | 手动触发增量检测，输出有变化的分类 |

**注意**: `./run.sh sync` 将同步任务放入后台运行（`&`）。

## 配置 (config.yml)

```yaml
es:
  host: http://localhost:59200
  index: ods_material_jinan_price        # 材料价格主索引
  catalogue_index: material_jinan_price_catalogue  # 分类目录索引
  progress_index: ods_material_jinan_price_sync_progress  # 进度记录索引
  sync_log_index: ods_material_jinan_price_sync_log        # 同步日志索引
site:
  base_url: http://jnxxj.jngczjxh.com:5020
  api_base: /cj/api/build
  data_type: '2'    # 信息价材料类型
sync:
  last_period: 2026年04月材料价格信息
  last_period_id: '800251371103429'
  size_per_page: 100
```

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_jinan_price` | 材料价格数据 |
| `material_jinan_price_catalogue` | 分类目录 |
| `ods_material_jinan_price_sync_progress` | 同步进度（运行状态、分类、页码、百分比、耗时） |
| `ods_material_jinan_price_sync_log` | 同步日志 |

## 数据字段

| 字段 | 说明 |
|------|------|
| `breed` | 材料名称（productName） |
| `spec` | 规格型号（features） |
| `unit` | 单位 |
| `price` / `tax_price` | 含税价格（infoPrice） |
| `period` / `period_id` | 周期名称 / ID |
| `province` | 山东 |
| `city` / `county` | 济南 |
| `catalogue` / `catalogue_name` | 分类 ID / 名称 |
| `code` | 材料编码 |
| `update_date` | 更新日期（从 publishTime 提取） |
| `publish_time` | 发布时间 |

## 幂等写入

```
_id = MD5(breed + spec + period + period_id + catalogue_id + price)
```

## 断点续传

本地进度保存至 `.jinan_sync_progress.json`，记录 `catalogue_id`、`period_id`、`period_name`、`page`、`total_records`、`docs_written`。中断后 `./run.sh sync` 自动从断点恢复。

## 增量机制

1. **周期维度**: 获取网站最新 `periodId`，与 `config.yml` 中 `last_period_id` 对比，不同则触发全量同步
2. **分类记录数维度**: 同周期内，逐分类对比网站实际唯一记录数与 ES `doc_count`，有差异触发增量同步（精确遍历去重）

## 项目结构

```
jinan-price/
├── run.sh
├── config.yml
├── .jinan_sync_progress.json    # 本地进度（自动生成）
└── commands/
    ├── sync.py      # 同步主程序（后台运行）
    ├── preview.py  # 数据预览
    ├── status.py   # 进度查看
    ├── test.py     # 连接测试
    ├── check.py    # 增量检测
    └── utils.py    # JinAnSiteSession、ES 索引创建、配置加载
```

## 依赖

- Python 3
- `requests` / `beautifulsoup4` / `pyyaml`
- `playwright` + `chromium`（用于从浏览器 localStorage 获取 token）
- Elasticsearch（`http://localhost:59200`）

安装依赖：
```bash
pip3 install requests beautifulsoup4 pyyaml playwright
playwright install chromium
```
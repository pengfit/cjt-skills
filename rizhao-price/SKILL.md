---
name: rizhao-price
description: "日照工程造价材料信息采集：从 http://58.59.43.227:81 抓取材料价格数据。"
---

# rizhao-price

从日照工程造价信息网站 `http://58.59.43.227:81` 抓取材料价格数据，通过 Playwright 浏览器自动化实现流式抓取，写入本地 ES。

## 功能特性

- **流式抓取**：单次浏览器启动，连续翻页，边抓边写 ES，无需大量内存
- **三个数据类别**：建设工程材料 / 园林绿化苗木 / 区县建设工程材料
- **增量同步**：自动检测网站期数和每 tab 记录数变化，按需同步
- **断点续传**：本地保存进度，中断后从断点恢复
- **幂等写入**：`_id = MD5(breed + spec + unit + period + price + city + county)`，重复运行不产生重复数据

## 数据源

- **URL**：`http://58.59.43.227:81/dist/#/index/priceDissemination`（Vue + ElementUI 动态页面）
- **Chrome 路径**：`/Users/pengfit/Library/Caches/ms-playwright/chromium-1217/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing`
- **数据来源字段**：`clmc`(材料名称)、`ggxh`(规格型号)、`dw`(单位)、`price`(参考价格)，从页面表格提取

## 命令速查

| 命令 | 说明 |
|------|------|
| `./run.sh preview` | 预览前 N 页数据（默认 2 页）|
| `./run.sh preview --pages 3 --type 2` | 预览 tab2 前 3 页 |
| `./run.sh sync` | 增量同步（当前 tab）|
| `./run.sh sync --force` | 全量同步（所有 tab）|
| `./run.sh sync --type 2` | 指定 tab 同步（1/2/3）|
| `./run.sh sync --no-check` | 跳过增量检测直接同步 |
| `./run.sh sync --max-pages N` | 最大页数（默认 2000）|
| `./run.sh sync --dry-run` | 预览模式，不写入 ES |
| `./run.sh sync --reset` | 重置进度，从头开始 |
| `./run.sh check` | 手动增量检测（不写入）|
| `./run.sh status` | 查看同步状态 |
| `./run.sh test` | 测试 ES 和源站连接 |

## 三个数据类别

| tab_type | 名称 | 说明 |
|----------|------|------|
| `1` | 建设工程材料 | 主数据，约 1083 条 |
| `2` | 园林绿化苗木 | 苗木类，约 7 条 |
| `3` | 区县建设工程材料 | 按区县区分的工程材料，约 60 条 |

## 配置（config.yml）

```yaml
es:
  host: http://localhost:59200           # ES 服务地址
  index: ods_material_rizhao_price       # 数据索引
  progress_index: ods_rizhao_price_progress  # 进度索引
  sync_log_index: ods_rizhao_price_sync_log # 同步日志索引

site:
  base_url: http://58.59.43.227:81/EpointSDRZ
  price_page: http://58.59.43.227:81/dist/#/index/priceDissemination

sync:
  last_period: "2026-04"                # 上次同步期数（自动更新）
```

## 数据字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `breed` | text | 材料名称 |
| `spec` | text | 规格型号 |
| `unit` | keyword | 单位 |
| `price` | float | 参考价格（元）|
| `period` | keyword | 期数（如 2026-03）|
| `province` | keyword | 山东 |
| `city` | keyword | 日照市 |
| `county` | keyword | 区县（tabType=3 时区分）|
| `tab_type` | keyword | 类别 ID（1/2/3）|
| `tab_name` | keyword | 类别名称 |
| `update_date` | date | 更新日期（period-01）|
| `create_time` | date | 入库时间 |

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_rizhao_price` | 材料价格数据 |
| `ods_rizhao_price_progress` | 同步运行记录 |

## 增量机制

**增量检测逻辑**（`check.py`）：

1. **周期维度**：网站当前期数 vs `config.yml` 中 `last_period` → 不同则触发全量同步所有 tab
2. **tab 维度**：同周期内，逐 tab 对比网站 `totalCount` vs ES `doc_count` → 有差异则触发该 tab 增量同步

每次同步后自动更新 `last_period`。

## 断点续传

- 进度保存至本地 `.rizhao_sync_progress.json`（tab_type / period / page / total_pages / docs_written）
- 中断后 `./run.sh sync` 自动识别并从断点页续传

## 项目结构

```
rizhao-price/
├── run.sh               # CLI 入口（封装各命令）
├── config.yml           # 配置文件
├── package.json         # npm 依赖（playwright）
├── .rizhao_sync_progress.json  # 本地进度文件（自动生成）
└── commands/
    ├── sync.py          # 同步主程序（流式版）
    ├── preview.py       # 数据预览
    ├── check.py         # 增量检测
    ├── status.py        # 同步状态查询
    ├── test.py          # 连接测试
    ├── fetch_data.js    # Playwright 浏览器抓取（三种模式）
    └── utils.py         # 共用函数、ES 索引创建、配置加载
```

## 依赖

- **Python 3** + `requests` `pyyaml`
- **Node.js** + `playwright`（需提前 `npx playwright install chromium`）
- **本地 ES**：`http://localhost:59200`
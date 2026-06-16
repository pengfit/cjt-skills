---
name: qingdao-price
description: "青岛工程造价材料信息采集：从 sjw.qingdao.gov.cn 抓取每月《青岛市建设工程材料价格》PDF，存到 minio 并入库到 ods_material_qingdao_price。"
---

# qingdao-price

青岛工程造价材料信息采集 Skill。从 `sjw.qingdao.gov.cn`（青岛市住房和城乡建设局）"建材价格信息" 栏目抓取每月发布的《青岛市建设工程材料价格》PDF，上传 MinIO，解析为长表（材料×规格×单位×价格），按月周期增量同步至本地 ES，写入 `ods_material_qingdao_price`。

## 数据流

```
sjw.qingdao.gov.cn/cxjsj13/cxjs_95/cxjsj_zj5/ (列表，无分页)
       ↓ fetch
列表 (N 期) → 详情页 → PDF 链接
       ↓ download (需 Referer) + upload
MinIO: gov-price-data/qingdao-price/{period}/source.pdf
       ↓ pdfplumber.extract_tables
长表 (材料 × 规格 × 单位 × 含税价/不含税价)
       ↓ bulk_index
ods_material_qingdao_price
```

## 快速启动

```bash
cd skills/qingdao-price

./run.sh preview                  # 预览（不写入 ES、不上传 minio）
./run.sh preview --period 2026.5  # 指定周期预览
./run.sh sync                     # 同步最新一期到 ES + minio
./run.sh sync --period 2026.5     # 指定周期同步
./run.sh sync --all               # 同步所有未入仓的期
./run.sh sync --reset             # 重置进度，从头开始
./run.sh status                   # 查看同步状态
```

## 数据源

- **列表页**：`https://sjw.qingdao.gov.cn/cxjsj13/cxjs_95/cxjsj_zj5/`
  - 一页内全部列表项，无分页
  - 列表项：`<li trs-attr="chip"><a target="_blank" href="...t{YYYYMMDD}_{ID}.html" title="2026年M月青岛市建设工程材料价格">`
- **详情页**：`http://sjw.qingdao.gov.cn/cxjsj13/cxjs_95/cxjsj_zj5/{YYYYMM}/t{YYYYMMDD}_{ID}.html`
- **PDF 链接**：
  - 详情页正文：`<a href="./P{YYYYMMDD}{ID}.pdf" download="2026年M月青岛市建设工程材料价格.pdf">`
  - 旧路径：`oldsrc="/protect/P{YYYYMMDD-prefixed-path}/P{YYYYMMDD}{ID}.pdf"`
  - **下载必须带 Referer 头**（指向详情页），否则 501 Not Implemented
- **PDF 内部月份**：`YYYY年M月青岛市建设工程材料价格` → 周期 `2026.M月`
- **PDF 结构**：
  - Page 1: 5月主要建材价格行情（文字分析）
  - Page 2: 主要建材价格走势图（图表）
  - Page 3-8: 材料价格表，每页一个分类（一/钢材、二/水泥、三/门窗、四/……）
  - 表头：`序号 | 名称 | 规格型号 | 单位 | 含税价(元)`
  - **全部为含税价** → 程序按 9% 增值税率反推 `price`（不含税价）
  - **单城市**：仅青岛市一个 city 标签

## 数据字段

| 字段 | 说明 |
|------|------|
| `breed` | 材料名称 |
| `spec` | 规格型号 |
| `unit` | 单位 |
| `price` | 不含税价（按 9% 增值税反推） |
| `tax_price` | 含税价（PDF 原始价格） |
| `period` | 周期（`2026.5月`） |
| `province` | 山东 |
| `city` | 青岛 |
| `update_date` | 发布日期（列表上的 `YYYY-MM-DD`） |
| `create_time` | 入库时间 |
| `source_pdf` | MinIO PDF 路径 |
| `source_url` | PDF 原始 URL |

## 幂等写入

```
_id = MD5(period + breed + spec + unit + price)
```

## 断点续传

本地进度保存至 `.qingdao_sync_progress.json`，记录 `detail_url`、`period`、`publish_date`、`docs_written`、`status`。中断后 `./run.sh sync` 自动从断点恢复。

## 项目结构

```
qingdao-price/
├── run.sh
├── config.yml
├── .qingdao_sync_progress.json    # 本地进度（自动生成）
└── commands/
    ├── sync.py      # 同步主程序
    ├── preview.py  # 数据预览
    ├── status.py   # 进度查看
    ├── test.py     # 连接测试
    └── utils.py    # 配置加载、ES、MinIO、HTTP 工具
```

## 依赖

- Python 3
- `requests` / `beautifulsoup4` / `pyyaml`
- `pdfplumber`（PDF 表格抽取）
- `boto3`（MinIO S3 客户端）
- `elasticsearch`（ES 客户端）
- Elasticsearch（`http://localhost:59200`）
- MinIO（`http://localhost:9000`，bucket `gov-price-data`）

安装依赖：
```bash
pip3 install requests beautifulsoup4 pyyaml pdfplumber boto3 elasticsearch
```

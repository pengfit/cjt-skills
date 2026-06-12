---
name: henan-price
description: "河南工程造价材料信息采集：从 www.hncost.com 抓取全省 18 个地级市材料价格 PDF 表格，存到 minio 并入库到 ods_material_henan_price。"
---

# henan-price

河南工程造价材料信息采集 Skill。从 `www.hncost.com`（河南省工程造价信息网）抓取"材料价格查询"模块每期的 PDF 附件，上传 MinIO，解析为长表（材料×规格×单位×地市×价格），按月周期增量同步至本地 ES，写入 `ods_material_henan_price`。

## 数据流

```
www.hncost.com (列表 4 页) 
       ↓ fetch
列表 (16 期) → 详情页 → PDF 链接
       ↓ download + upload
MinIO: gov-price-data/henan-price/{period}/source.pdf
       ↓ pdfplumber.extract_tables
长表 (材料 × 18 个地市价格)
       ↓ bulk_index
ods_material_henan_price
```

## 快速启动

```bash
cd skills/henan-price

./run.sh preview                  # 预览（不写入 ES、不上传 minio）
./run.sh preview --period 2026.3  # 指定周期预览
./run.sh sync                     # 同步最新一期到 ES + minio
./run.sh sync --period 2026.3     # 指定周期同步
./run.sh sync --all               # 同步所有未入仓的期
./run.sh sync --reset             # 重置进度，从头开始
./run.sh status                   # 查看同步状态
```

## 数据源

- **列表页**：`http://www.hncost.com/jcxx/004001/subpage2.html` (含分页 1-4)
- **详情页**：`/jcxx/004001/{YYYYMMDD}/{uuid}.html`
- **PDF 附件**：`/BigFileUpLoadStorage/temp/{YYYY-MM-DD}/{uuid}/{filename}.pdf`
- **标题格式**：`河南省YYYY年M1-M2月建设工程材料价格信息`（如"河南省2026年3-4月"）
- **PDF 内部月份**：`YYYY.N月`（如"2026.3月"）
- **页数**：约 131 页（约 60 个"材料组"，每组 = 1 主表页 + 0~1 续表页）

## 18 个地市

郑州、濮阳、周口、许昌、新乡、洛阳、安阳、焦作、平顶山、信阳、漯河、驻马店、南阳、鹤壁、三门峡、济源、开封、商丘

## 数据字段

| 字段 | 说明 |
|------|------|
| `breed` | 材料名称 |
| `spec` | 规格型号 |
| `unit` | 单位 |
| `price` | 价格（不含税） |
| `period` | 周期（PDF 内部月份 `2026.3月`） |
| `province` | 河南 |
| `city` | 地市 |
| `update_date` | 发布日期（列表上的 `YYYY-MM-DD`） |
| `create_time` | 入库时间 |
| `source_pdf` | MinIO 对象 key |

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_henan_price` | 材料价格数据 |
| `ods_material_henan_price_sync_progress` | 同步进度记录 |

## 幂等写入

```
_id = MD5(period + breed + spec + city)
```

> 同一 (breed, spec, city) 在 PDF 中可能出现 2 次（主表页前 5 地市 + 续表页后 13 地市），
> 不含 price 的 _id 让后写覆盖前写，去重后约 966 条 / 期（原始解析 ~1932 行）。
> PDF 中部分地市无数据的格子会被跳过（如商丘某期某材料）。

## 项目结构

```
henan-price/
├── SKILL.md
├── config.yml
├── run.sh
├── .henan_sync_progress.json
└── commands/
    ├── sync.py        # 主同步（列表→详情→PDF→minio→ES）
    ├── preview.py     # 预览（不写入）
    ├── status.py      # 进度查询
    ├── test.py        # ES + minio + 源站连通性
    └── utils.py       # 配置加载、minio 客户端、ES 客户端
```

## 依赖

- Python 3
- requests / beautifulsoup4 / pyyaml
- pdfplumber
- boto3 (MinIO S3 兼容)
- elasticsearch

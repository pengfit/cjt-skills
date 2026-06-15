# henan-price

河南省工程造价材料价格数据采集。

> 📘 详细 Skill 描述见 [SKILL.md](./SKILL.md)

## 简介

从 [河南省工程造价信息网](http://www.hncost.com) 抓取"材料价格查询"模块每期发布的 PDF 附件，下载、上传 MinIO，解析为长表（材料 × 18 个地市价格），写入 ES `ods_material_henan_price`。

## 快速开始

```bash
cd skills/henan-price

# 1. 测试连通性（ES + MinIO + 源站）
./run.sh test

# 2. 预览最新一期（不写入）
./run.sh preview --latest

# 3. 同步最新一期
./run.sh sync --latest

# 4. 同步指定年份
./run.sh sync --year 2026

# 5. 查看同步状态
./run.sh status
```

## 目录结构

```
henan-price/
├── SKILL.md                  # Skill 描述（接口契约）
├── README.md                 # 本文件（开发与使用）
├── config.yml                # ES / MinIO / 源站 / 18 地市配置
├── run.sh                    # 入口脚本
├── .henan_sync_progress.json # 本地进度（每期 OK/FAILED）
└── commands/
    ├── sync.py               # 主同步：列表 → 详情 → PDF → MinIO → 解析 → ES
    ├── preview.py            # 预览（不写入 ES / MinIO）
    ├── status.py             # 进度查询（本地 + ES + MinIO）
    ├── test.py               # ES / MinIO / 源站连通性
    └── utils.py              # 配置加载、MinIO 客户端、ES 客户端、HTTP 工具
```

## 数据流

```
hncost.com 列表 4 页（~49 期）
   ↓ fetch
详情页 + PDF 链接
   ↓ download
本地临时 PDF (~4.5MB / 131 页)
   ↓ upload
MinIO: gov-price-data/henan-price/{period}/source.pdf
   ↓ pdfplumber.extract_tables
长表 (材料 × 18 地市价格，~1932 行/期)
   ↓ bulk_index
ods_material_henan_price (~966 条/期，_id 去重)
```

## 关键设计

### 跨页续表拼接
PDF 跨页设计：每"材料组" = 1 主表页（前 5 地市）+ 0~1 续表页（后 13 地市）。
`_parse_one_table()` 识别主表/续表，主表填入 (breed, spec, unit) 列表 + 5 地市，续表按行序补全 13 地市。

### 幂等 _id
```python
_id = MD5(period + breed + spec + city)
```
不含 price：同 (breed, spec, city) 在 PDF 中可能跨组出现多次，后写覆盖前写。

### 分类标题行跳过
PDF 中"1 水泥"、"2 砂浆"等分类标题被识别为 `breed=水泥, spec='', unit='', prices=[None, ...]`，通过 `if not breed and not spec and not unit: continue` 跳过。

## 配置

`config.yml` 主要字段：
- `es.host` / `es.ods_index` / `es.progress_index`
- `minio.endpoint` / `minio.bucket` / `minio.prefix`
- `site.base_url` / `site.list_path` / `site.list_pages`
- `cities`: 18 个地市列表（识别续表页用）

## 依赖

```
requests
beautifulsoup4
pdfplumber
boto3
elasticsearch
pyyaml
```

## 调试

```bash
# 直接跑 Python（输出未缓冲）
python3 -u commands/sync.py --latest

# 单期 dry-run
python3 -u commands/sync.py --period 2026.3月 --dry-run

# 跳过网络，单测 PDF 解析
python3 -c "
import sys; sys.path.insert(0, 'commands')
from sync import parse_pdf_tables
print(len(parse_pdf_tables('/path/to/source.pdf', [])))
"
```

## 已知限制

- PDF 续表页按行序对齐（pdfplumber 行数有时不准），个别材料的续表价格可能错位
- PDF 中部分地市格空（缺数据）会跳过
- 暂未接入 `gov-price-etl`（需在 `etl.py` 的 `CITY_CONFIGS` 注册 `henan`）

## 关联

- 上游：`http://www.hncost.com/jcxx/004001/subpage2.html`
- 下游：政府材料价格 Dashboard（消费 ES 数据）
- 同类：`sichuan-price` / `chongqing-price` / `jinan-price` / `rizhao-price` / `xian-price`

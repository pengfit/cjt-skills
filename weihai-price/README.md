# weihai-price

威海工程造价材料价格数据采集。

> 📘 详细 Skill 描述见 [SKILL.md](./SKILL.md)

## 简介

从 [威海市住房和城乡建设局](https://zjj.weihai.gov.cn/col/col28584/index.html) 抓取"通知公告"栏目里每期发布的《威海市主要工程建设材料信息价》PDF（2026 年起改"信息价"），下载、上传 MinIO，解析为长表（材料 × 规格 × 单位 × 信息价），写入 ES `ods_material_weihai_price`。

## 快速开始

```bash
cd skills/weihai-price

# 1. 测试连通性（ES + MinIO + 源站 + 依赖）
./run.sh test

# 2. 预览最新一期（不写入）
./run.sh preview --latest

# 3. 同步 2026 年所有期
./run.sh sync --year 2026

# 4. 同步指定周期
./run.sh sync --period 2026.1-3月

# 5. 查看同步状态
./run.sh status
```

## 目录结构

```
weihai-price/
├── SKILL.md                  # Skill 描述（接口契约）
├── README.md                 # 本文件（开发与使用）
├── config.yml                # ES / MinIO / 源站配置
├── skill.yml                 # dashboard 注册声明（key=weihai）
├── run.sh                    # 入口脚本
├── .weihai_sync_progress.json # 本地进度（每期 OK/FAILED）
└── commands/
    ├── sync.py               # 主同步：列表 → 详情 → PDF → MinIO → 解析 → ES
    ├── preview.py            # 预览（不写入 ES / MinIO）
    ├── status.py             # 进度查询（本地 + ES + MinIO）
    ├── check.py              # 增量检测
    ├── test.py               # ES / MinIO / 源站连通性
    └── utils.py              # 配置加载、MinIO 客户端、ES 客户端、HTTP 工具
```

## 数据流

```
zjj.weihai.gov.cn 通知公告 21 页（301 条）共 12 条价目相关
   ↓ POST dataproxy.jsp (groupSize=3, 7 次抓完)
详情页 + PDF 下载链接
   ↓ HTTP GET (downfile.jsp 302 → /attach/0/xxx.pdf)
本地临时 PDF (~232KB / 27 页, 公示版 274KB / 29 页)
   ↓ upload
MinIO: gov-price-data/weihai-price/{period}/{filename}.pdf
   ↓ pdfplumber.extract_tables + extract_text
长表 (材料 × 规格 × 单位 × 信息价，~816 条/期，10 分类)
   ↓ bulk_index
ods_material_weihai_price (~911 unique / 期，_id 去重)
```

## 关键设计

### 公示版 PDF 兼容
"公示"版 PDF（附件 2）的分类行 "一、水泥、地材" 在 body 文本中而非表内。
`parse_pdf_tables()` 先 `extract_text()` 扫描 `^([一二...十])、([一-鿿、·\d A-Za-z（）()]+)$` 模式作为 category，再 `extract_tables()` 抽数据。

### groupSize 分页
jpage 插件 groupSize=3，每次返回 3×15=45 条 record。
`fetch_list_page(cfg, page)` 中 `page` 是"组号"（1~7），不是"页号"（1~21）。
`startrecord = (page-1) * 15 * 3 + 1`，`endrecord = page * 15 * 3`。

### 幂等 _id
```python
_id = MD5(period + breed + spec + unit + price)
```
同一 (breed, spec, unit, price) 在最终版 PDF 和公示版 PDF 中重复出现 → 后写覆盖前写。

## 配置

`config.yml` 主要字段：
- `es.host` / `es.ods_index` / `es.progress_index`
- `minio.endpoint` / `minio.bucket` / `minio.prefix`
- `site.base_url` / `site.list_path` / `site.list_proxy`
- `site.list_webid` / `list_columnid` / `list_unitid` / `list_per_page` / `list_total_record`
- `city` / `province` / `price_type`
- `sync.default_year` （默认 2026）

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
python3 -u commands/sync.py --year 2026

# 单期 dry-run
python3 -u commands/sync.py --period 2026.1-3月 --dry-run

# 跳过网络，单测 PDF 解析
python3 -c "
import sys; sys.path.insert(0, 'commands')
from sync import parse_pdf_tables
print(len(parse_pdf_tables('/path/to/source.pdf', '威海')))
"
```

## 已知限制

- 同一期数据可能有两个 PDF（最终版 + 公示版），公示版（附件 2）通常多 2 页，且首页分类行在表外（已在 `parse_pdf_tables()` 中兼容）
- PDF 内部"信息价"为不含税价（与山东其他城市一致）
- PDF 内表头用空格分隔时偶尔被 pdfplumber 抽错列数（4 列 vs 5 列），已做容错
- 通知公告列表每页都用 groupSize=3 抓，21 页分 7 次抓完；totalRecord 实际 301（不是 316，每次会抓到上组的少量重复，已按 detail_url 去重）

## 关联

- 上游：`https://zjj.weihai.gov.cn/col/col28584/index.html`
- 下游：`gov-price-etl`（ODS → DWD → DWS 三段式清洗 + v3 分类 + 规格解析）
- 下游：`gov-price-dashboard`（消费 DWS 数据，材价通可视化）
- 同类：`qingdao-price` / `heze-price` / `henan-price` / `sichuan-price` / `chongqing-price` / `jinan-price` / `rizhao-price` / `xian-price`

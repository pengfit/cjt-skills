---
name: weihai-price
description: "威海工程造价材料信息采集：从 zjj.weihai.gov.cn 抓取每季度《威海市主要工程建设材料信息价》PDF，存到 minio 并入库到 ods_material_weihai_price。"
---

# weihai-price

威海工程造价材料信息采集 Skill。从 `zjj.weihai.gov.cn`（威海市住房和城乡建设局）"通知公告"栏目（`/col/col28584`）抓取"主要工程建设材料信息价"或"部分工程建设材料指导价格"每期发布的 PDF（通过 `dataproxy.jsp` POST 接口 + `downfile.jsp` 302 重定向），上传 MinIO，解析为长表（材料×规格×单位×信息价），按期增量同步至本地 ES，写入 `ods_material_weihai_price`。

## 数据流

```
zjj.weihai.gov.cn/col/col28584 (通知公告，共 21 页)
       ↓ fetch_list_page (POST dataproxy.jsp, groupSize=3, 7 次抓完)
通知列表 (含"主要工程建设材料信息价"等条目)
       ↓ 详情页
downfile.jsp (302 → /attach/0/xxx.pdf)
       ↓ download_file
本地 PDF (~232KB / 27 页, 公示版 274KB / 29 页)
       ↓ upload_to_minio
MinIO: gov-price-data/weihai-price/{period}/{filename}.pdf
       ↓ pdfplumber.extract_tables + extract_text
长表 (材料 × 规格 × 单位 × 信息价，~816 条/期，10 分类)
       ↓ bulk_index
ods_material_weihai_price (~911 unique / 期，_id 去重)
```

## 快速启动

```bash
cd skills/weihai-price

./run.sh test                       # 连通性测试（ES + MinIO + 源站 + 依赖）
./run.sh preview                    # 预览（不写入）
./run.sh preview --year 2026        # 指定年份预览
./run.sh preview --latest           # 只预览最新一期
./run.sh sync                       # 同步（按 config.yml 的 default_year=2026）
./run.sh sync --year 2026           # 指定年份
./run.sh sync --period 2026.1-3月   # 指定周期
./run.sh sync --all                 # 同步所有未入仓的期
./run.sh sync --reset               # 重置进度，从头开始
./run.sh status                     # 同步状态（本地 + ES + MinIO）
./run.sh check                      # 增量检测（不写入）
```

## 数据源

- **通知公告列表**：`https://zjj.weihai.gov.cn/col/col28584/index.html`（共 21 页 × 15 条 = 301 条通知）
  - **列表 API**：`/module/web/jpage/dataproxy.jsp`（POST，jpage 插件）
  - **参数**：`col=1, webid=93, columnid=28584, unitid=428350, webname=威海市住房和城乡建设局, permissiontype=0`
  - **分页**：`groupSize=3`（每次返回 3 组 × 15 = 45 条），共 7 次抓完
- **详情页**：`/art/{YYYY}/{M}/{DD}/art_28584_{ID}.html`
  - 标题：`<div class="top"><h1>威海市2026年1-3月份主要工程建设材料信息价</h1></div>`
- **PDF 下载**：`/module/download/downfile.jsp?classid=0&showname={name}.pdf&filename={hash}.pdf`
  - 302 重定向到 `/attach/0/{hash}.pdf`
  - **同一数据可能有两个 PDF**：最终版（2026-05-25 发布）和公示版（附件 2，2026-04-30 发布）
- **PDF 内部周期标识**：`威海市2026年1-3月份主要工程建设材料信息价` → 周期 `2026.1-3月`
- **页数**：27 页（最终版）/ 29 页（公示版）；约 60+ 行/页 = 816 条 unique 数据

## 数据字段

| 字段 | 说明 |
|------|------|
| `breed` | 材料名称 |
| `spec` | 规格型号 |
| `unit` | 单位 |
| `price` | 信息价（不含税价） |
| `category` | PDF 内分类（一、水泥、地材 / 二、钢材 / ... / 十、市政材料） |
| `period` | 周期（`2026.1-3月`） |
| `province` | 山东 |
| `city` | 威海 |
| `update_date` | 发布日期（列表上的 `YYYY-MM-DD`） |
| `create_time` | 入库时间 |
| `source_pdf` | MinIO 对象 key |
| `source_url` | PDF 原始 URL |

## 10 个分类

- 一、水泥、地材
- 二、钢材
- 三、木材
- 四、门窗
- 五、防水材料
- 六、保温材料
- 七、安装材料
- 八、涂料
- 九、装饰材料
- 十、市政材料

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_weihai_price` | 材料价格数据 |
| `ods_material_weihai_price_sync_progress` | 同步进度记录 |

## 幂等写入

```
_id = MD5(period + breed + spec + unit + price)
```

同一 (breed, spec, unit, price) 在最终版 PDF 和公示版 PDF 中重复出现 → 去重后 ~911 条 unique（公示版与最终版可能存在 50~100 条 price 微调差异）。

## 关键设计

### 公示版 PDF 兼容
"公示"版 PDF（附件 2）的分类行 "一、水泥、地材" 在 body 文本中而非表内。
`parse_pdf_tables()` 先 `extract_text()` 扫描 `^([一二...十])、([一-鿿、·\d A-Za-z（）()]+)$` 模式作为 category，再 `extract_tables()` 抽数据。

### groupSize 分页
jpage 插件 groupSize=3，每次返回 3×15=45 条 record。
`fetch_list_page(cfg, page)` 中 `page` 是"组号"（1~7），不是"页号"（1~21）。
`startrecord = (page-1) * 15 * 3 + 1`，`endrecord = page * 15 * 3`。

### 302 重定向
`downfile.jsp` 302 → `/attach/0/xxx.pdf`，`requests` 默认 follow，无需特殊处理。

## 项目结构

```
weihai-price/
├── SKILL.md
├── README.md
├── config.yml
├── skill.yml                  # dashboard 注册声明
├── run.sh
├── .weihai_sync_progress.json # 本地进度（自动生成）
└── commands/
    ├── sync.py        # 主同步（列表 → 详情 → PDF → minio → ES）
    ├── preview.py     # 预览（不写入）
    ├── status.py      # 进度查询
    ├── check.py       # 增量检测
    ├── test.py        # 连通性
    └── utils.py       # 配置加载、minio 客户端、ES 客户端、HTTP 工具
```

## 依赖

- Python 3
- `requests` / `beautifulsoup4` / `pyyaml`
- `pdfplumber`（PDF 表格抽取）
- `boto3`（MinIO S3 客户端）
- `elasticsearch`（ES 客户端）
- Elasticsearch（`http://localhost:59200`）
- MinIO（`http://localhost:9000`，bucket `gov-price-data`）

## 关联

- 上游：`https://zjj.weihai.gov.cn/col/col28584/index.html`
- 下游：`gov-price-etl`（ODS → DWD → DWS 三段式清洗 + v3 分类 + 规格解析）
- 下游：`gov-price-dashboard`（消费 DWS 数据，材价通可视化）
- 同类：`qingdao-price` / `heze-price` / `henan-price` / `sichuan-price` / `chongqing-price` / `jinan-price` / `rizhao-price` / `xian-price`

## 已知限制

- 同一期数据可能有两个 PDF（最终版 + 公示版），公示版（附件 2）通常多 2 页，且首页分类行在表外（已在 `parse_pdf_tables()` 中兼容）
- PDF 内部"信息价"为不含税价（与山东其他城市一致）
- PDF 内表头用空格分隔时偶尔被 pdfplumber 抽错列数（4 列 vs 5 列），已做容错
- 通知公告列表每页都用 groupSize=3 抓，21 页分 7 次抓完；totalRecord 实际 301（不是 316，每次会抓到上组的少量重复，已按 detail_url 去重）

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

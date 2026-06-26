---
name: hainan-price
description: "海南工程造价材料信息采集：从 zjt.hainan.gov.cn 抓取每月《海南省建设工程主要材料、园林绿化苗木、施工机具与周转材料租赁市场参考价》PDF，存到 minio 并入库到 ods_material_hainan_price。"
---

# hainan-price

海南工程造价材料信息采集 Skill。从 `zjt.hainan.gov.cn`（海南省住房和城乡建设厅）抓取"价格信息"栏目每月发布的 PDF 附件，上传 MinIO，解析为长表（编号×材料×规格×单位×单价×备注），按月周期增量同步至本地 ES，写入 `ods_material_hainan_price`。

> **当前数据范围**：2026.1月 ~ 2026.4月（已入库 13048 条）。**2026.5月 暂未入库**——源站从该月起改为字符级图像 PDF（每字段为 JPEG 图像），`pdfplumber.extract_tables()` 拿不到数据，需走 OCR 路径（待定）。历史期按需补录。

## 数据流

```
zjt.hainan.gov.cn (列表 ~15 页 × 10 条)
       ↓ fetch
列表 (149 期) → 详情页 → PDF 链接
       ↓ download + upload
MinIO: gov-price-data/hainan-price/{period}/source.pdf
       ↓ pdfplumber.extract_tables
长表 (编号 × 材料 × 规格 × 单位 × 单价 × 备注)
       ↓ bulk_index
ods_material_hainan_price
```

## 快速启动

```bash
cd skills/hainan-price

./run.sh preview                  # 预览（不写入 ES、不上传 minio）
./run.sh preview --period "2026年1月"  # 指定周期预览（按 title 模糊匹配）
./run.sh sync                     # 同步最新一期到 ES + minio
./run.sh sync --period "2026年1月"     # 指定周期同步
./run.sh sync --year 2026 --exclude-period "2026年5月"  # 同步 2026 年全部（跳过图像型 PDF 期）
./run.sh sync --all               # 同步所有未入仓的期
./run.sh sync --reset             # 重置进度，从头开始
./run.sh status                   # 查看同步状态
```

## 数据源

- **列表页**：`https://zjt.hainan.gov.cn/szjt/dejgxx/dezlist.shtml?ddtab=true`
  - 分页：`dezlist_2.shtml`、`dezlist_3.shtml` ...（每页 10 条，共 ~15 页 149 期）
  - 分页由 JS `createPageHTML('page_div',10, 1,'dezlist','shtml',149)` 生成
- **详情页**：`/szjt/dejgxx/{YYYYMM}/{uuid}.shtml`
- **PDF 附件**：`/szjt/dejgxx/{YYYYMM}/{uuid}/files/{file_uuid}.pdf`
- **标题格式**：`YYYY年M月海南省建设工程主要材料、园林绿化苗木及施工机具与周转材料租赁市场参考价`（如"2026年5月海南省..."）
- **PDF 内部月份**：`YYYY年M月`（如"2026年1月"）→ 统一为 `2026.1月`
- **页数**：约 159 页

## 价格口径

- **信息价 = 不含税可抵扣进项税市场信息价（除税价）**，适用于一般计税方法工程项目
- 含税价 / 不含税价 = 1 + 9% 增值税率（VAT_RATE = 0.09）
- 各分类（黑色金属 / 水泥 / 木材 / 玻璃 / 砖瓦 / 陶瓷 / 油漆 / 塑料 / 五金 / 门窗 / 防水 / 电线电缆 / 消防 / 成品 / 园林绿化 / 机械 / 装饰 / 周转 / 其它 / 人工机械台班）合并到 1 个 city="海南"

## 数据字段

| 字段 | 说明 |
|------|------|
| `no` | 编号（PDF 中"10013"等 5 位数字） |
| `breed` | 材料名称 |
| `spec` | 规格型号 |
| `unit` | 单位 |
| `price` | 单价（不含税） |
| `tax_price` | 单价（含税），从 price 反推：`price * (1 + 0.09)` |
| `remark` | 备注（耐火等级、用途、执行标准等） |
| `category` | 大类（黑色金属 / 水泥及水泥制品 / ...） |
| `period` | 周期（PDF 内部月份 `2026.1月`） |
| `province` | 海南 |
| `city` | 海南（全省指导价） |
| `update_date` | 发布日期（列表上的 `YYYY-MM-DD`） |
| `create_time` | 入库时间 |
| `source_pdf` | MinIO 对象 key |
| `source_url` | PDF 原始 URL |

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_hainan_price` | 材料价格数据 |
| `ods_material_hainan_price_sync_progress` | 同步进度记录 |

## 幂等写入

```
_id = MD5(period + no + breed + spec)
```

> PDF 中同一 (breed, spec) 不会出现重复（每行 = 1 个编号 + 1 个规格）。
> 部分材料按"分左右两栏"排版，需在解析时按列拆分后合并。

## 项目结构

```
hainan-price/
├── SKILL.md
├── config.yml
├── run.sh
├── .hainan_sync_progress.json
└── commands/
    ├── sync.py        # 主同步（列表→详情→PDF→minio→ES）
    ├── preview.py     # 预览（不写入）
    ├── status.py      # 进度查询
    ├── test.py        # ES + minio + 源站连通性
    └── utils.py       # 配置加载、minio 客户端、ES 客户端
```

## PDF 形态变化（2026.5月 起为图像型）

源站 PDF 从 **2026 年 5 月起改为字符级图像 PDF**：每个数据字段（序号/材料名称/规格/单位/价格）都是独立的 JPEG 图像，PDF 的 text 流只剩表头文字。**`pdfplumber.extract_tables()` 拿不到任何数据**（表格边框识别到，但单元格内容是空）。

诊断特征：

| 特征 | text PDF（2026.1-4月） | image PDF（2026.5月+） |
|---|---|---|
| p11 页 chars | ~800 | ~50 |
| p11 页 images | 0 | ~350 |
| extract_tables() 数据行 | ~28 | 0 |
| parse_pdf() 解析条数 | ~3300 / 期 | ~140 / 期（仅苗木-乔木 价格） |

**短期处理**：用 `--exclude-period "2026年5月"` 跳过该期。

**长期方案（待定）**：
- OCR（paddleocr 中文场景）：~10-15 分钟 / 期，覆盖完整
- 图像哈希匹配 1-4月已知数据：覆盖率 ~70-80%（5月独有值拿不到）

## Dashboard 注册

为了让 `gov-price-dashboard` 自动发现本 skill，根目录需要 `skill.yml`（小写）：

```yaml
key: hainan
label: 海南
province: 海南
ods_index: ods_material_hainan_price
dwd_index: dwd_hainan_price
dws_index: dws_hainan_price
progress_index: ods_material_hainan_price_sync_progress
progress_mode: period          # 每月一期，与 henan/heze/qingdao/weihai 同模式
expand_label: "▾ 期数详情"
config_path: config.yml
cities:
  - 海南
  - 北部
  - 南部
  - 西部
  - 东部
  - 中部
```

dashboard 扫描 `~/.openclaw/workspace/skills/*/skill.yml` 自动注册。修改后调用 `POST /api/skill-registry/reload` 触发重扫。

## 依赖

- Python 3
- requests / beautifulsoup4 / pyyaml
- pdfplumber
- boto3 (MinIO S3 兼容)
- elasticsearch

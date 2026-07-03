---
name: hainan-price
description: "海南工程造价材料信息采集：从 zjt.hainan.gov.cn 抓取每月《海南省建设工程主要材料、园林绿化苗木、施工机具与周转材料租赁市场参考价》PDF，存到 minio 并入库到 ods_material_hainan_price。v0.8 改用 chongqing-style SyncRunner 抽象基类。"
---

# hainan-price

海南工程造价材料信息采集 Skill。从 `zjt.hainan.gov.cn`（海南省住房和城乡建设厅）抓取"价格信息"栏目每月发布的 PDF 附件，上传 MinIO，解析为长表（编号×材料×规格×单位×单价×备注），按月周期增量同步至本地 ES，写入 `ods_material_hainan_price`。

> **当前数据范围**：2026.1月 ~ 2026.4月（已入库 **13,048 条**）。**2026.5月 暂未入库**——源站从该月起改为字符级图像 PDF（每字段为 JPEG 图像），`pdfplumber.extract_tables()` 拿不到数据，需走 OCR 路径（待定）。历史期按需补录。

## v0.8 模块建构（参照重庆 chongqing-price，2026-07-02）

参照 `chongqing_collector.py`（v0.8 SyncRunner 抽象基类试点）改造：

| 文件 | 角色 | 说明 |
|------|------|------|
| `commands/sync.py` | CLI 入口（薄壳） | 参数解析 → 委托给 `hainan_collector` |
| `commands/hainan_collector.py` | **主流程** | `HainanCollector(SyncRunner)` 重写 `_list_work_units / _process_one / _on_unit_done / _compute_unit_key` |
| `commands/parser.py` | **纯函数库** | `parse_list_page / fetch_all_periods / parse_detail_page / parse_pdf / extract_period_from_title / bulk_index / _doc_id` 等 |
| `commands/utils.py` | 工具 + mapping | `load_config / ensure_ods_index / ensure_progress_index`；ODS mapping 补 hainan 特化字段（region/section） |
| `commands/preview.py` | 预览 | 独立工具，从 `parser` 导入纯函数（不写 ES/minio） |
| `commands/check.py` | 增量检测 | 独立工具，对比 ES 最新 update_date vs 源站最新发布 |
| `commands/status.py` | 进度查询 | 本地 JSON + ES 进度索引双视角 |
| `commands/test.py` | 连通性测试 | ES + MinIO + 源站 |
| `commands/resync_from_minio.py` | **MinIO 应急重入** | 跳过源站下载，直接读 MinIO 里已有的 PDF 重新入 ES（适用于源站慢/不可达，但本地 PDF 已下载的场景） |

> 进度文件 `.hainan_sync_progress.json` 仍是 `{'done': {detail_url: {...}}}` 结构，
> 兼容历史数据；`HainanCollector` 用 `_load_old_progress()` 做格式桥接。

## 快速启动

```bash
cd skills/hainan-price

./run.sh preview                  # 预览（不写入 ES、不上传 minio）
./run.sh preview --period "2026年1月"
./run.sh sync                     # 同步最新一期到 ES + minio
./run.sh sync --period "2026年1月"
./run.sh sync --year 2026 --exclude-period "2026年5月"  # 同步 2026 年全部（跳过图像型 PDF 期）
./run.sh sync --all               # 同步所有未入仓的期
./run.sh sync --reset             # 重置本地进度
./run.sh sync --max-units 1       # 只跑 1 期（验证用）
./run.sh status                   # 查看同步状态
./run.sh check                    # 增量检测
./run.sh test                     # ES + MinIO + 源站连通性
```

## 数据流

```
zjt.hainan.gov.cn (列表 ~10 页 × 15 条)
       ↓ fetch
列表 (149 期) → 详情页 → PDF 链接
       ↓ download + upload (PDF 下载内置 3 次重试)
MinIO: gov-price-data/hainan-price/{period}/source.pdf
       ↓ pdfplumber.extract_tables
长表 (编号 × 材料 × 规格 × 单位 × 单价 × 备注)
       ↓ bulk_index（mapping 含 hainan 特化字段 region/section）
ods_material_hainan_price
```

## 数据源

- **列表页**：`https://zjt.hainan.gov.cn/szjt/dejgxx/dezlist.shtml`
  - 分页：`dezlist_2.shtml`、`dezlist_3.shtml` ...（每页 15 条，共 10 页 149 期）
  - 分页由 JS `createPageHTML(...)` 生成
- **详情页**：`/szjt/dejgxx/{YYYYMM}/{uuid}.shtml`
- **PDF 附件**：`/szjt/dejgxx/{YYYYMM}/{uuid}/files/{file_uuid}.pdf`
- **标题格式**：`YYYY年M月海南省建设工程主要材料、园林绿化苗木及施工机具与周转材料租赁市场参考价`
- **PDF 内部月份**：`YYYY年M月` → 统一为 `2026.1月`
- **页数**：约 159 页/期

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
| `region` | 区域（北部 / 南部 / 西部 / 东部 / 中部 / 全省）— hainan 特化字段 |
| `section` | 一级章节（钢材 / 水泥、砂石、墙体材料和预制桩 / ...）— hainan 特化字段 |
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

### Mapping 特化（v0.8 2026-07-02 补）

基础 ODS mapping（`gov_price_etl.mappings.build_ods_mapping`）是 `dynamic=strict`，
要求采集器在 `ensure_ods_index` 时通过 `city_extension` 声明所有非标准字段。
hainan 在 `utils.py` 补了两个特化字段：

```python
mapping = build_ods_mapping(city_extension={
    "region":  {"type": "keyword"},  # 北部/南部/西部/东部/中部/全省
    "section": {"type": "keyword"},  # 钢材/水泥/装配式/... 一级章节
})
```

## 幂等写入

```
_id = MD5(period + region + section + no + breed + spec)
```

> PDF 中同一 (breed, spec) 不会出现重复（每行 = 1 个编号 + 1 个规格）。
> 部分材料按"分左右两栏"排版，需在解析时按列拆分后合并。

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

## PDF 下载重试（v0.8 新增）

hainan 源站偶发 `Connection broken: IncompleteRead`（中间断连），
`hainan_collector._process_one` 在 PDF 下载环节内置 **3 次重试**（间隔 3s/6s/9s），
不传播给 SyncRunner。

## 依赖

- Python 3
- requests / beautifulsoup4 / pyyaml
- pdfplumber
- boto3 (MinIO S3 兼容)
- elasticsearch
- gov_price_etl（提供 `SyncRunner` 抽象基类 + `build_ods_mapping` + ES/MinIO 客户端）

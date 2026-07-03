---
name: "jiangxi-price"
description: "江西建设工程材料价格采集：zjt.jiangxi.gov.cn《江西省造价信息》期刊，列表页 articleList JSON 抓 PDF，按期刊期数入库到 ods_material_jiangxi_price。"
---

# jiangxi-price

江西省住房和城乡建设厅"工程造价"-"江西省造价信息"-"各期常用材料价格参考信息"栏目《江西省材料价格参考信息》期刊采集。从 `zjt.jiangxi.gov.cn/jxszfhcxjst/gqcyc/pc/list.html` 抓取列表（页面里 `var articleList = [...]` 直接嵌入 JSON），下载 PDF，上传 MinIO，pdfplumber 解析为长表，按期刊期数同步至 ES，写入 `ods_material_jiangxi_price`。

> 🆕 **v0.9（2026-07-03）**：SyncRunner 抽象基类化 + 必含字段 `period / period_start / period_end / period_days`（道友要求）
>  - `sync.py` 默认走 `JiangxiCollector`（SyncRunner 抽象基类实现），`--legacy` 保留 v0.8 逃生通道
>  - period 窗口按 publish_date 所在月计算（例：`2026-06-05` → `2026-06-01 ~ 2026-06-30, 30d`）

> **当前数据范围**：2026 年第 1 期（2026-02-05）~ 2026 年第 5 期（2026-06-05），共 **38774 条**。
> 列表还含 2025 年各期（12 期），按需扩展。**只保留标题含"江西省材料价格参考信息"的期**。
> 用户要求**只同步 2026 年的期**（第1-5期），通过 `--year 2026` 控制。

## 数据流

```
zjt.jiangxi.gov.cn/jxszfhcxjst/gqcyc/pc/list.html (列表 HTML)
   ↓ 解析 var articleList = [...] 嵌入 JSON
列表 (每期: title, pubDate, articleFiles[0].filePath, domainName)
   ↓ journal_keyword 过滤（"江西省材料价格参考信息"）
   ↓ year 过滤（2026 年）
   ↓ 不访问详情页（PDF URL 在 articleList 直接给）
PDF URL (http://zjt.jiangxi.gov.cn/jxszfhcxjst/gqcyc/{id}/{hash}.pdf)
   ↓ download (requests → curl -k 回退，处理老旧 SSL renegotiation)
PDF (90-100 页, ~1-2 MB)
   ↓ upload
MinIO: gov-price-data/jiangxi-price/{period}/{basename}.pdf
   ↓ pdfplumber.extract_tables
   ↓ 3 种表格类型：
      - 17 列全省表（序号/类别/名称/规格/单位/11城市/税率）→ melt
      - 14-17 列多县表（序号/名称/规格/单位/多县/税率/备注）→ melt
      - 6-7 列设区市补充表（序号/材料价格/规格/单位/信息参考价/税率/备注）→ 直接长表
      - 7 列单县/单市表（宁都县/乐平市）→ 直接长表
      - 9 列园林苗木表 → 直接长表
长表
   ↓ bulk_index
ods_material_jiangxi_price
```

## PDF 结构

| 章节 | 内容 | 表头结构 | 是否解析 |
|---|---|---|---|
| 全省各设区市价格信息 | 17 列：序号/材料类别/材料名称/规格型号/单位/11城市/税率 | ✅ 主体（melt）|
| 各设区市补充部分地材 | 7 列：序号/材料价格/规格型号/单位/信息参考价/税率/备注 | ✅ 主体 |
| 各设区市补充部分地材（无备注 6 列，如抚州 p54）| 6 列：序号/材料价格/规格型号/单位/信息参考价/税率 | ✅ 主体 |
| 各县（市、区）工程常用材料价格汇总表 | 14-17 列：序号/材料名称/规格/单位/N 县/税率/备注 | ✅ 主体（melt）|
| 单县表（宁都县 7 列）| 7 列：序号/材料名称/规格及型号/单位/宁都县/税率/备注 | ✅ 主体 |
| 单市表（乐平市 6 列）| 6 列：序号/材料名称/规格及型号/单位/乐平市/税率 | ✅ 主体 |
| 园林苗木信息参考价 | 9 列：序号/苗木名称/胸径/地径/高度/冠幅/单位/信息参考价/税率 | ✅ 主体 |
| 勘误（p92）| 错误更正表 | ❌ 跳过 |

## 字段映射

| 字段 | 来源 |
|---|---|
| `period` | title 提取：`江西省材料价格参考信息2026年第5期` → `2026.第5期` |
| `period_start` | publish_date 所在月首日（例：`2026-06-05` → `2026-06-01`） |
| `period_end` | publish_date 所在月末日（例：`2026-06-30`） |
| `period_days` | 当月天数（28-31） |
| `category` | 全省表 = "阀门类"/"金属材料"等；其他 = "材料价格" 或 "园林苗木" |
| `section` | 章节标题（如"全省各设区市" / "南昌市补充部分地材信息参考价" / "赣州市宁都县工程材料信息参考价"） |
| `city` | 设区市名（如"南昌" / "九江" / "景德镇"）|
| `region` | 县名（多县表填县名）|
| `no` | 表格首列（材料序号 1-N）|
| `breed` | 材料名称 |
| `spec` | 规格型号（园林苗木组合"胸径xx 高度xx 冠幅xx"）|
| `unit` | 计量单位 |
| `price` | 信息参考价（**PDF 给的已是含税价**）|
| `tax_price` | 等于 price |
| `vat_rate` | 增值税税率（PDF 直接读：0.13 / 0.03 / 0.09）|
| `price_kind` | `含税`（PDF 给的已是含税价）|

## 章节命名差异

不同期 PDF 的章节命名略有差异：

| 期 | 章节命名 |
|---|---|
| 2026 年第 1-2 期 | "南昌市工程常用地方材料信息参考价"（独有）|
| 2026 年第 3-5 期 | "南昌市补充部分地材信息参考价" |
| 2026 年第 1-2 期 | "赣州市宁都县工程材料信息参考价"（独有）|
| 2026 年第 3-5 期 | "赣州市宁都县常用材料价格汇总表" |
| 2026 年第 1-2 期 | "景德镇乐平市工程常用材料信息参考价"（独有）|
| 2026 年第 3-5 期 | "景德镇乐平市常用材料价格汇总表" |

> 数据归集时按 `section` 字段区分；下游分析时建议按"赣州市宁都县"模糊归一化。

## 快速启动

```bash
cd skills/jiangxi-price

./run.sh preview                    # 预览（不写入 ES、不上传 minio）
./run.sh preview --year 2026         # 只预览 2026 年的期
./run.sh preview --latest            # 只预览最新一期
./run.sh sync --year 2026            # 同步 2026 年所有期（默认走 Collector 路径）
./run.sh sync --year 2026 --max-units 1  # Collector 路径：只跑 1 期（验证用）
./run.sh sync --year 2026 --legacy   # 走 v0.8 legacy 路径（逃生通道，不推荐）
./run.sh sync --year 2026 --exclude-period "2026年第1期"  # 跳过某期（仅 legacy 生效）
./run.sh sync --all                  # 同步所有未入仓的期
./run.sh status                      # 查看同步状态
./run.sh check                       # 增量检测（不写入）
./run.sh test                        # ES / MinIO / 源站连通性测试
```

## Dashboard 注册

为了让 `gov-price-dashboard` 自动发现本 skill，根目录需要 `skill.yml`（小写）：

```yaml
key: jiangxi
label: 江西
province: 江西
ods_index: ods_material_jiangxi_price
progress_index: ods_material_jiangxi_price_sync_progress
progress_mode: period          # 按期刊期数跟踪
expand_label: "▾ 期数详情"
config_path: config.yml
cities:
  - 南昌市
  - 九江市
  - 上饶市
  - 抚州市
  - 宜春市
  - 吉安市
  - 赣州市
  - 景德镇市
  - 萍乡市
  - 新余市
  - 鹰潭市
```

dashboard 扫描 `~/.openclaw/workspace/skills/*/skill.yml` 自动注册。修改后调用 `POST /api/skill-registry/reload` 触发重扫 + 热更新 ALL_INDICES。

## 依赖

- Python 3
- requests / beautifulsoup4 / pyyaml
- pdfplumber
- boto3 (MinIO S3 兼容)
- elasticsearch
- **curl**（SSL renegotiation 失败时回退到老旧政府网站）

## 已知限制

- **SSL renegotiation 问题**：江西省住建厅 zjt.jiangxi.gov.cn 用老旧 TLS 配置（`unsafe_legacy_renegotiation_disabled`），Python `requests` 默认拒绝。`utils.py` 的 `fetch_html` / `download_file` 在 `requests.exceptions.SSLError` 时自动回退到 `curl -k` 命令。
- **PDF 字间距重复字符**：部分 PDF 标题行字符被 PDF 渲染为双倍间距（如"赣州市价格信息" → "赣赣州州市市价价格格信信息息"），导致字符串匹配失败。`_detect_page_kind` / `_detect_current_city` / 章节识别 regex 都使用 `re.sub(r'(.)\1+', r'\1', head)` 折叠重复字符后再匹配。
- **章节命名跨期差异**：2026 年第 1-2 期 和第 3-5 期 的章节命名格式不同（详见上文），数据归集需注意 `section` 字段。
- **价格含税/不含税方向**：PDF 直接给"信息参考价"+ 单独"增值税税率"列，价格已是含税价。`price == tax_price`，`vat_rate` 从表里读。
- **勘误页不解析**（p92，错误更正表）
- **续表识别依赖 current_section 继承**：当 PDF 续表页不含"2026年X月"开头的章节标题时，依赖前一页的 `current_section` 继承。已测试 5 期 2026 年 PDF 全部正确归类。

## 当前解析覆盖

| 期 | publish_date | period_start | period_end | period_days | 总条数 |
|---|---|---|---|---|---|
| 2026年第1期 | 2026-02-05 | 2026-02-01 | 2026-02-28 | 28 | 7,573 |
| 2026年第2期 | 2026-03-10 | 2026-03-01 | 2026-03-31 | 31 | 7,513 |
| 2026年第3期 | 2026-04-03 | 2026-04-01 | 2026-04-30 | 30 | 8,265 |
| 2026年第4期 | 2026-05-08 | 2026-05-01 | 2026-05-31 | 31 | 7,697 |
| 2026年第5期 | 2026-06-05 | 2026-06-01 | 2026-06-30 | 30 | 7,726 |
| **合计** | | | | | **38,774** |

v0.9 (2026-07-03) 同步：5 期全部走 Collector 路径，duration=66s，每期都含 period_start/end/days 字段。

## 项目结构

```
jiangxi-price/
├── SKILL.md
├── config.yml
├── skill.yml
├── run.sh                            # ./run.sh {preview|sync|status|check|test}
├── .jiangxi_sync_progress.json       # 本地进度（断点续传）
├── .jiangxi_sync_progress.v0.8.bak   # v0.8 旧进度备份
└── commands/
    ├── sync.py                       # v0.9 主入口：默认 JiangxiCollector，--legacy 走 v0.8
    ├── jiangxi_collector.py          # v0.9 SyncRunner 抽象基类化主类
    ├── utils.py                      # ES/MinIO 工具 + ensure_ods/progress_index
    ├── preview.py                    # 预览（dry-run）
    ├── status.py                     # 查看本地 + ES + MinIO 状态
    ├── check.py                      # 增量检测（ES vs 源站）
    └── test.py                       # ES/MinIO/源站连通性
```

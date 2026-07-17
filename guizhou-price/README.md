# 贵州 · 工程造价材料信息采集

> 数据源:`http://www.gzszj.com/Home/Policies/c2a45b5e-fb3e-43c6-a77c-000000000046`(子 tab: 工程造价信息)
> 进度模式:`period` · 时间方法:2026 年(道友要求) · 12 期/年(月刊)
> ETL 索引:`ods_material_guizhou_price` → `dwd_guizhou_price` → `dws_guizhou_price`

贵州工程造价材料信息采集, 从 gzszj.com(贵州省建设工程造价管理协会)的"造价信息 → 工程造价信息"子 tab 抓取月刊 PDF, 按期期刊跟踪, 同步至 Elasticsearch + MinIO, 供下游 ETL/Dashboard 消费。

## 功能特性

- **进度模式**:`period` — 按 `YYYY.N期` 业务标识跟踪(道友指定"时间方法 2026 年", 默认仅入库 2026 年期)
- **数据获取**:AJAX POST 翻页(`/Home/GetPoliciesListBy`),不是 HTML 静态列表
- **断点续传**:本地 `.guizhou_sync_progress.json` + ES `ods_material_guizhou_price_sync_progress`, 中断自动恢复
- **幂等写入**:ES `_id` = MD5(period + breed + spec + city), placeholder 行加 `source_pdf` 区分
- **PDF 归档**:所有抓到期的 PDF 都上传到 MinIO (`gov-price-data/guizhou-price/<pdf_name>`)
- **可降级**:支持 `--legacy` 走老 v0.7 流程(`cmd_legacy_sync`)
- **v0.8 字段扩展**:doc 中新增 `period_start / period_end / period_days`

## 快速开始

```bash
cd <skills>/guizhou-price

# 1) 连通性自检
./run.sh test

# 2) 预览本期(下载 PDF 试解析, 不写 ES / MinIO)
./run.sh preview --latest
# 或预览指定期: ./run.sh preview --period="2026.6期"

# 3) 增量同步(默认仅 2026 年, 走 SyncRunner Collector)
./run.sh sync

# 4) 全量同步(不限年份)
./run.sh sync --all

# 5) 看状态
./run.sh status
./run.sh check

# 6) 调试:只跑前 3 期
./run.sh sync --max-units=3

# 7) 逃生:走 v0.7 legacy
./run.sh sync --legacy --dry-run
```

## 配置说明

`config.yml` 主要字段:

```yaml
es:
  host: http://localhost:59200                          # ES 地址
  ods_index: ods_material_guizhou_price                  # ODS 主索引
  progress_index: ods_material_guizhou_price_sync_progress  # 进度索引

minio:
  endpoint: http://localhost:9000
  bucket: gov-price-data
  prefix: guizhou-price                                  # 对象前缀

site:
  base_url: http://www.gzszj.com
  list_path: /Home/Policies/c2a45b5e-fb3e-43c6-a77c-000000000046  # 造价信息 tab
  ajax_path: /Home/GetPoliciesListBy                     # AJAX 列表端点
  sub_tab_guid: c2a45b5e-fb3e-43c6-a77c-000000004601    # 工程造价信息子 tab
  page_size: 20                                          # 每页期数

sync:
  default_year: 2026                                     # 道友要求"时间方法 2026 年"
```

## 数据流

```
gzszj.com AJAX POST
   ↓ commands/sync.py (--legacy)
   或 commands/guizhou_collector.py (v0.8 Collector, 默认)
   ↓
ods_material_guizhou_price  ──→  MinIO (gov-price-data/guizhou-price/<pdf>)
   ↓ <skills>/gov-price-etl cli/etl.py --city guizhou
dwd_guizhou_price
   ↓ cli/sync_dws.py --city guizhou --mode quick
dws_guizhou_price  ──→  <skills>/gov-price-dashboard
```

## 数据获取机制(关键差异 vs henan)

不同于 henan 的 HTML 静态列表页, gzszj.com 是 **.NET CMS (Zoomla!)**, 列表数据通过 AJAX POST 获取:

- **请求**: `POST /Home/GetPoliciesListBy`
- **Headers**: `Referer + X-Requested-With: XMLHttpRequest + Content-Type: application/x-www-form-urlencoded`
- **Body**: `guid={sub_tab_guid}&page={N}&pagesize=20`
- **响应**: `{"Rows":[{ID, Name, EntryDate("/Date(ms)/"), PoliciesAttachmentDTOS:[{FileUrl}]}], "Total":N}`

PDF 直链拼装:

```
base_url + "/Upload/File/" + quote(FileUrl, safe="/")
```

其中 `FileUrl` 形如 `{uuid}/贵州省建设工程造价信息-2026第6期.pdf`, 中文部分需 `urllib.parse.quote(safe='/')`。

## 周期命名

源站期号: `贵州省建设工程造价信息 YYYY年第N期`
业务标识: `YYYY.N期`(issue N, 月刊)

| 期号 | period | period_start | period_end | period_days |
|------|--------|--------------|------------|-------------|
| `2026年第1期` | `2026.1期` | `2026-01-01` | `2026-01-31` | `31` |
| `2026年第6期` | `2026.6期` | `2026-06-01` | `2026-06-30` | `30` |
| `2026年第12期` | `2026.12期` | `2026-12-01` | `2026-12-31` | `31` |

## ES 文档字段

```json
{
  "period":        "2026.6期",
  "period_start":  "2026-06-01",
  "period_end":    "2026-06-30",
  "period_days":   30,
  "breed":         "圆钢 Φ10",
  "spec":          "HPB300",
  "unit":          "t",
  "price":         3850.00,
  "city":          "贵州",
  "province":      "贵州",
  "update_date":   "2026-06-22",
  "create_time":   "2026-07-16T06:09:00",
  "source_pdf":    "guizhou-price/贵州省建设工程造价信息-2026第6期.pdf",
  "source_url":    "http://www.gzszj.com/Upload/File/{uuid}/{name}.pdf",
  "parse_status":  "parsed"   // or "unparsed" (仅归档, 待人工解析)
}
```

## 常见问题

- **断点续传**: 进度写入本地 `.guizhou_sync_progress.json` + ES `ods_material_guizhou_price_sync_progress`, 中断后 `./run.sh sync` 自动续传(基于 `unit.detail_url` 做 key)。
- **幂等写入**: `_id` = MD5(period + breed + spec + city), placeholder 行加 `source_pdf`, 重复同步不会产生重复数据。
- **增量检测**: `./run.sh check` 对比 ES 最新 `update_date` vs 源站最新一期发布日期, 输出 `🔔 有更新` / `✅ 无新数据`。
- **PDF 解析未识别**: 默认解析 4-6 列"材料名称/规格型号/单位/单价"简单表格。复杂版式首次跑后看 `preview` 输出, 在 `commands/sync.py` 的 `_classify_cols` / `parse_pdf_tables` 调整列关键字。
- **源站过滤年份**: `--year=2026` 只入库 2026 年; `--all` 解除过滤; 不传默认用 `config.sync.default_year=2026`。

## 调试技巧

```bash
# 看最新一期到底拿到了什么
./run.sh preview --latest

# 调试 Collector 流程(只跑 1 期, 看完整日志)
./run.sh sync --latest --run-id=test_run_$(date +%s)

# 强制重跑某期
rm -f .guizhou_sync_progress.json && ./run.sh sync --year=2026

# 看 ES 进度索引
curl -s 'http://localhost:59200/ods_material_guizhou_price_sync_progress/_search?size=10&pretty&sort=created_at:desc'

# 看 MinIO 上的 PDF
mc ls myminio/gov-price-data/guizhou-price/
```

## 相关

- `<skills>/gov-price-dashboard` — 看板(查 DWS 数据)
- `<skills>/gov-price-etl` — ETL 公共层
- `<skills>/gov-price-etl/SKILL.md` — ETL 使用文档
- `<skills>/henan-price` — 参考模板(同 v0.8 SyncRunner 结构)

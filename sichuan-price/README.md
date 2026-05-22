# 四川工程造价材料信息采集工具

从 http://202.61.90.35:8032/pubpages/pricelist.aspx 抓取四川省 21 个地级市/自治州材料价格数据，同步至本地 Elasticsearch。

## 支持地区（21 个）

川A(成都市)、川B(绵阳市)、川C(自贡市)、川D(攀枝花市)、川E(泸州市)、川F(德阳市)、川H(广元市)、川J(遂宁市)、川K(内江市)、川L(乐山市)、川M(资阳市)、川Q(宜宾市)、川R(南充市)、川S(达州市)、川T(雅安市)、川U(阿坝州)、川V(甘孜州)、川W(凉山州)、川X(广安市)、川Y(巴中市)、川Z(眉山市)

## 快速开始

```bash
cd ~/.openclaw/workspace/skills/sichuan-price

# 全量同步（自动获取最新周期）
./run.sh sync

# 预览数据（不写入）
./run.sh preview --pages 3

# 指定周期同步
./run.sh sync --period "2026年03月"

# 强制全量同步（跳过增量检测）
./run.sh sync --force

# 断点续传（自动）
./run.sh sync      # Ctrl+C 中断后，重启自动续传
```

## 同步参数

| 参数 | 说明 |
|------|------|
| `--period` | 指定周期（默认自动获取最新）|
| `--force` | 强制全量同步，跳过增量检测 |
| `--reset` | 重置进度，从头开始 |
| `--max-pages N` | 每地区最大页数（默认 2000）|
| `--no-check` | 跳过增量检测，直接同步 |

## 增量逻辑

按**时间周期**判断：程序自动从网站获取最新周期（State=1），与 config 中 `last_period` 对比。若相同则跳过，不同则全量同步。

## 数据结构

ASP.NET POST 分页，每页 25 条记录。材料数据行为纵向（材料名/规格/单位），城市/区县为横向列。一条材料 × 一城市 = 1 条 ES 文档。

## 幂等写入

文档以 `MD5(breed+spec+period+price+tax_price+city+county)` 作为 `_id`，重复同步不会产生重复数据。价格变化生成新文档，保留历史。

## 配置文件

`config.yml` 控制 ES 连接：

```yaml
es:
  host: http://localhost:59200
  index: material_sichuan_price
  sync_progress_index: material_sichuan_price_sync_progress

site:
  url: http://202.61.90.35:8032/pubpages/pricelist.aspx

sync:
  last_period: ""   # 上次同步周期（自动维护）
```

## 项目结构

```
sichuan-price/
├── README.md
├── SKILL.md
├── run.sh              # 入口脚本
├── config.yml          # ES/站点配置
└── commands/
    ├── sync.py         # 同步主程序（ProgressLogger 写入 ES 进度）
    ├── preview.py      # 预览模式（不写入 ES）
    ├── status.py       # 查看同步状态
    ├── test.py         # 测试 ES 连接
    ├── test_pages.py   # 测试分页
    ├── test_types.py   # 测试类型
    ├── check.py        # 检查源站是否有新数据
    └── utils.py        # SiteSession、parse_page、ensure_index、AREA_CODES
```

## 依赖

- Python 3
- requests
- beautifulsoup4
- pyyaml
- Elasticsearch 7.x / 8.x
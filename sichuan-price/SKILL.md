---
name: sichuan-price
description: "四川工程造价材料信息采集：从 202.61.90.35:8032 抓取四川省 21 个地级市/自治州材料价格数据。"
---

# sichuan-price

四川工程造价材料信息采集。从 `202.61.90.35:8032` 抓取四川省 21 个地级市/自治州材料价格数据，按月周期增量同步至本地 ES，写入 `ods_material_sichuan_price`。

## 快速启动

```bash
cd skills/sichuan-price

./run.sh preview              # 预览（不写入 ES）
./run.sh preview --pages 3    # 预览前 3 页
./run.sh preview --area 川A   # 指定地区预览
./run.sh preview --period "2026年03月"  # 指定周期预览
./run.sh sync                 # 全量同步到 ES
./run.sh sync --force         # 强制全量，跳过增量检测
./run.sh sync --dry-run       # 预览同步（不写入）
./run.sh sync --no-check      # 跳过增量检测直接同步
./run.sh sync --max-pages 500  # 限制每地区页数（默认 2000）
./run.sh sync --reset         # 重置进度，从头开始
./run.sh sync --period "2026年03月"   # 指定周期
./run.sh status               # 查看同步状态
./run.sh test                 # 测试 ES 连接
./run.sh check                # 手动增量检测
```

## 数据流

```
202.61.90.35:8032 → sync.py → ods_material_sichuan_price
                                      ↓
                            gov-price-etl (etl.py)
                                      ↓
                            dwd_sichuan_price
                                      ↓
                            sync_dws.py
                                      ↓
                            dws_sichuan_price
```

## 支持地区（21 个）

川A(成都市)、川B(绵阳市)、川C(自贡市)、川D(攀枝花市)、川E(泸州市)、川F(德阳市)、川H(广元市)、川J(遂宁市)、川K(内江市)、川L(乐山市)、川M(资阳市)、川Q(宜宾市)、川R(南充市)、川S(达州市)、川T(雅安市)、川U(阿坝州)、川V(甘孜州)、川W(凉山州)、川X(广安市)、川Y(巴中市)、川Z(眉山市)

## 数据字段

| 字段 | 说明 |
|------|------|
| `breed` | 材料名称 |
| `spec` | 规格型号 |
| `unit` | 单位 |
| `price` | 原始价格 |
| `tax_price` | 含税价格 |
| `is_tax` | 是否含税 |
| `period` | 周期名称（如 2026年03月）|
| `province` | 四川 |
| `city` | 城市/区县（来自横向列）|
| `update_date` | 更新日期（period 转换） |
| `create_time` | 入库时间 |

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_sichuan_price` | 材料价格数据 |
| `ods_material_sichuan_price_sync_progress` | 同步进度记录 |
| `ods_material_sichuan_price_sync_log` | 同步日志 |

## 幂等写入

```
_id = MD5(breed + spec + period + price + tax_price + city + county)
```

## 断点续传

进度保存到 `.sichuan_sync_progress.json`，中断后 `./run.sh sync` 自动续传。

## 项目结构

```
sichuan-price/
├── run.sh
├── config.yml
├── .sichuan_sync_progress.json
└── commands/
    ├── sync.py         # 同步主程序
    ├── preview.py      # 预览
    ├── check.py        # 增量检测
    ├── status.py       # 状态
    ├── test.py         # ES 连接测试
    ├── test_pages.py   # 分页测试
    ├── test_types.py   # 类型测试
    └── utils.py        # SiteSession、parse_page、AREA_CODES
```

## 依赖

- Python 3
- requests / beautifulsoup4 / pyyaml
- elasticsearch
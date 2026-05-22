# rizhao-price

日照工程造价材料信息采集。从 `58.59.43.227:81` 抓取日照市材料价格数据，支持多 tab、增量同步、断点续传。写入 `ods_material_rizhao_price`。

## 快速启动

```bash
cd skills/rizhao-price

./run.sh preview --pages 3    # 预览前 3 页
./run.sh sync                 # 增量同步到 ES
./run.sh sync --force         # 强制全量同步
./run.sh sync --reset         # 重置进度
./run.sh sync --type 1        # 指定类别（1=建设工程,2=园林绿化,3=区县材料）
./run.sh check                # 检查源站是否有新数据
./run.sh status               # 查看同步状态
```

## 数据流

```
58.59.43.227:81 → Node.js/Playwright → ods_material_rizhao_price
                                                    ↓
                                          gov-price-etl (etl.py)
                                                    ↓
                                          dwd_rizhao_price
                                                    ↓
                                          sync_dws.py
                                                    ↓
                                          dws_rizhao_price
```

## 技术方案

采用 Playwright 浏览器自动化 + 流式输出模式：
- `fetch_data.js` 提供 `stream` 模式：单次浏览器启动，连续翻页，每页实时输出 JSON Lines
- `sync.py` 通过 subprocess 管道驱动，实现边抓边写 ES

## 数据字段

| 字段 | 说明 |
|------|------|
| `breed` | 材料名称 |
| `spec` | 规格型号 |
| `unit` | 单位 |
| `price` | 参考价格 |
| `period` | 期数（如 2026-03）|
| `province` | 山东省 |
| `city` | 日照市 |
| `county` | 区县（tabType=3 时区分）|
| `tab_type` / `tab_name` | 类别 ID/名称 |

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_rizhao_price` | 材料价格数据 |
| `ods_rizhao_price_progress` | 同步进度记录 |

## 幂等写入

```
_id = MD5(breed + spec + unit + period + price + city + county)
```

## 断点续传

进度保存到 `.rizhao_sync_progress.json`，中断后 `./run.sh sync` 自动续传。

## 项目结构

```
rizhao-price/
├── run.sh
├── config.yml
├── package.json        # npm 依赖（playwright）
├── .rizhao_sync_progress.json
└── commands/
    ├── sync.py         # 同步主程序
    ├── preview.py
    ├── status.py
    ├── check.py
    ├── fetch_data.js   # Playwright 浏览器抓取
    └── utils.py
```

## 依赖

- Python 3
- Node.js + npm + playwright
- requests / pyyaml
- elasticsearch
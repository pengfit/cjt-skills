# xa-material-price

西安工程造价材料信息采集。从 `zjj.xa.gov.cn` 抓取西安 6 个区县材料价格数据，按更新日期增量同步至本地 ES，写入 `ods_material_xian_price`。

## 快速启动

```bash
cd skills/xa-material-price

./run.sh preview --pages 3    # 预览前3页（不写ES）
./run.sh sync                  # 增量同步（自动断点续传）
./run.sh sync --force          # 强制全量同步
./run.sh sync --reset          # 重置进度，从第1页重新开始
./run.sh sync --counties "蓝田县,周至县"   # 指定区县
./run.sh check                 # 增量检测
./run.sh status                # 查看同步状态
```

## 数据流

```
zjj.xa.gov.cn → sync.py → ods_material_xian_price
                                    ↓
                          gov-price-etl (etl.py)
                                    ↓
                          dwd_xian_price
                                    ↓
                          sync_dws.py
                                    ↓
                          dws_xian_price
```

## 支持区县（6个）

阎良区、临潼区、高陵区、鄠邑区、蓝田县、周至县

## 数据字段

| 字段 | 说明 |
|------|------|
| `code` | 材料编码 |
| `breed` | 材料名称 |
| `spec` | 规格型号 |
| `unit` | 单位 |
| `price` | 除税价格 |
| `tax_price` | 含税价格 |
| `county` | 区县 |
| `province` | 陕西 |
| `city` | 西安 |
| `update_date` | 更新时间（页脚解析） |
| `create_time` | 入库时间 |

## ES 索引

**ODS 索引**：`ods_material_xian_price`
**进度索引**：`ods_material_xian_price_sync_progress`

## 增量逻辑

基于更新时间判断：
1. 读取 ES 中该区县 `update_date` 最新记录
2. 抓取每页后解析页脚"更新时间"
3. 若 `更新时间 < ES 最新日期` → 停止（已无增量）
4. 若相等 → 继续抓取

## 断点续传

进度保存到 `.sync_progress.json`，中断后运行 `./run.sh sync` 自动续传。

## 幂等写入

```
_id = MD5(breed + code + spec + county + update_date + price + tax_price)
```

同一材料在同一区县、日期、价格下重复同步不会产生重复数据。

## 项目结构

```
xa-material-price/
├── run.sh           # 入口脚本
├── config.yml      # ES/站点配置
├── .sync_progress.json  # 进度文件（自动生成）
└── commands/
    ├── sync.py     # 同步主程序
    ├── check.py    # 增量检测
    ├── preview.py  # 预览（不写入ES）
    ├── status.py   # 状态查看
    ├── test.py     # ES连接测试
    └── utils.py    # SiteSession、解析工具
```

## 依赖

- Python 3
- requests
- beautifulsoup4
- pyyaml
- elasticsearch
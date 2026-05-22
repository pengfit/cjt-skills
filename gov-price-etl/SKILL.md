# gov-price-etl

政府材料价格数据清洗 ETL：将 `ods_material_{city}_price` 原始层清洗为 `dwd_{city}_price` 结构化层，再聚合为 `dws_{city}_price` 展示层。

## 数据流

```
ods_material_xian_price     ─┐
ods_material_sichuan_price    ─┤
ods_material_chongqing_price  ─┼─→ ETL ─→ dwd_{city}_price ─┐
ods_material_jinan_price       ─┤              ↓               │
ods_material_rizhao_price   ─┘       sync_dws ─→ dws_{city}_price
```

## 目录结构

```
gov-price-etl/
├── SKILL.md
├── config.yml
├── commands/
│   ├── __init__.py
│   ├── etl.py              # ODS → DWD 主程序
│   ├── parse_spec.py       # 规格解析规则库
│   ├── classify.py         # 品种分类引擎
│   ├── rules.py            # 分类规则库
│   └── clean.py            # 字段清洗
└── utils/
    └── sync_dws.py          # DWD → DWS 同步
```

## parse_spec 解析字段（ATTR_FIELDS）

| 字段 | 说明 | 示例 |
|------|------|------|
| `thickness` | 厚度 | `2mm`, `δ=4.5` |
| `length` | 长度 | `1000mm`, `1200*400` |
| `width` | 宽度 | `400mm` |
| `height` | 高度 | `600mm`, `H=0.36m→360mm` |
| `diameter` | 直径 | `150` |
| `material` | 材质 | `PE`, `PVC`, `铸铁` |
| `color` | 颜色 | `白`, `黑` |
| `grade` | 等级/牌号 | `Q235B`, `C30` |
| `cross_section` | 电缆截面 | `2.5mm²` |
| `cores` | 芯数 | `3芯` |
| `voltage` | 电压 | `220`, `380` |
| `current` | 电流 | `16A` |
| `asphalt_type` | 沥青类型 | `AC-13`, `SBSAC-13` |
| `cement_content` | 水泥含量 | `5%` |
| `channels` | 路数 | `8路` |
| `doors` | 门数 | `2门` |
| `drain_type` | 排水类型 | `下出水`, `地排水` |
| `installation_type` | 安装类型 | `台下盆`, `立柱盆` |
| `inlet_type` | 进水类型 | `后进水`, `上进水` |
| `length_range` | 长度范围 | `2~4m` |
| `height_range` | 高度范围 | `H100~H250`, `80-350mm高` |
| `temperature` | 温度 | `70℃` |
| `temp_range` | 温度范围 | `-10℃~50℃` |
| `humidity_range` | 湿度范围 | `0~100%RH` |
| `fiber_core` | 光纤芯数 | `12芯` |
| `media` | 介质 | `水` |
| `range` | 量程 | `0~1.8m` |
| `output` | 输出信号 | `4~20mA` |
| `cable_length` | 电缆长度 | `L=2.5m` |

## 分类体系（28 类）

钢材 / 水泥 / 石材 / 砂石骨料 / 保温材料 / 防水材料 / 管材管件 / 市政设施 / 装饰装修材料 / 涂料油漆 / 陶瓷卫生洁具 / 五金配件 / 密封材料 / 铜材 / 铝材铝合金 / 金属材料 / 绿化苗木 / 铁艺铸铁件 / 消防器材 / 网格布土工材料 / 化工材料 / 龙骨吊顶 / 瓦 / 公用事业费 / 机械设备 / 电气材料 / 劳务工种 / 其他

## 运行

```bash
cd skills/gov-price-etl

# 全量 ETL
python3 commands/etl.py

# 预览（前100条，不写入）
python3 commands/etl.py --dry-run
```

## DWD 输出字段

| 字段 | 说明 |
|------|------|
| `breed` | 原始品种名 |
| `breed_clean` | 清洗后品种名 |
| `spec` | 原始规格 |
| `spec_clean` | 清洗后规格（keyword） |
| `thickness` / `length` / `width` / `height` / `diameter` | 解析后尺寸字段 |
| 所有 ATTR_FIELDS | 细分字段（写入 DWS attr 对象） |
| `unit` | 标准单位 |
| `price` | 单价 |
| `tax_price` | 含税价 |
| `category` | 分类名称 |
| `province` / `city` / `county` | 地域信息 |
| `update_date` | 数据日期 |
| `etl_time` | ETL 时间戳 |

## DWS sync_dws

DWD → DWS 由 `utils/sync_dws.py` 完成，使用 ES bulk API 幂等写入（`_id` 保持一致）：

```python
import shutil, importlib.util
shutil.copy("commands/parse_spec.py", "/Users/pengfit/.openclaw/workspace/scripts/parse_spec.py")
spec = importlib.util.spec_from_file_location("sd", "utils/sync_dws.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.sync_dwd_to_dws()
```

## parse_spec 测试

```bash
python3 -c "
import importlib.util
spec = importlib.util.spec_from_file_location('ps', 'commands/parse_spec.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(m.parse_spec('H100~H250 Q235B'))
print(m.parse_spec('400*(800+250)'))
print(m.parse_spec('δ=4.5'))
print(m.parse_spec('混凝土预制井筒 Φ700 H=0.36m'))
"
```

## 数据索引对应

| 城市 | ODS 索引 | DWD 索引 | DWS 索引 |
|------|---------|---------|---------|
| 西安 | `ods_material_xian_price` | `dwd_xian_price` | `dws_xian_price` |
| 四川 | `ods_material_sichuan_price` | `dwd_sichuan_price` | `dws_sichuan_price` |
| 重庆 | `ods_material_chongqing_price` | `dwd_chongqing_price` | `dws_chongqing_price` |
| 济南 | `ods_material_jinan_price` | `dwd_jinan_price` | `dws_jinan_price` |
| 日照 | `ods_material_rizhao_price` | `dwd_rizhao_price` | `dws_rizhao_price` |
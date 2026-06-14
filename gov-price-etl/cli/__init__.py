"""cli - 入口脚本包

包含：
  - cli.etl       ODS → DWD → DWS 主入口
  - cli.sync_dws  DWD → DWS 同步（合一版）

直接运行：`./cli/etl ...` 或 `./cli/sync_dws ...`
也可用：`python3 -m cli.etl ...`（需要 PYTHONPATH=src）
"""

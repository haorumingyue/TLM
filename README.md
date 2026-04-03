# 煤流输送仿真与 Chronos-2 流量预测

## 目录说明

| 路径 | 说明 |
|------|------|
| `coal_conveyor_predict.py` | 主入口：仿真 + 双路预测（SIM / BACKTEST，见 `coal_conveyor/config.py` 中 `RUN_MODE`） |
| `coal_conveyor/` | 核心包：配置、数据解析、仿真、预测、回放、可视化、回测 |
| `coal_conveyor_web.py` | 主煤流协同控制系统 Web 入口（薄封装，逻辑在 `coal_conveyor_web/` 包内） |
| `coal_conveyor_web/` | Web 版：`config`（`WebConfig`）、数据、PID、仿真、预测、回放、`state`、`runtime`、`app`（Flask）、`templates/dashboard.html` |
| `data/` | 日志数据（`YYYYMMDD.txt`） |
| `models/chronos-2/` | Chronos-2 本地模型目录 |
| `docs/` | 文档（如调速策略说明） |
| `scripts/` | 维护脚本与独立工具（修补脚本、`predict_traffic.py` 等） |
| `legacy/` | 历史独立脚本（如仅皮带仿真、无预测的 `coal_conveyor_sim.py`） |
| `output/` | 运行生成的 HTML 等输出（回测图、预测结果等，默认写入此目录） |

## 运行方式

在项目根目录执行：

```bash
python coal_conveyor_predict.py
```

依赖见 `requirements.txt`。首次运行若缺包，`coal_conveyor/cli.py` 仍会尝试自动安装（与原先单文件行为一致）。

独立流量预测脚本（输出到 `output/forecast_result.html`）：

```bash
python scripts/predict_traffic.py
```

主煤流协同控制系统 Web 端（默认 `http://localhost:5173`，配置见 `coal_conveyor_web/config.py` 中 `WebConfig`）：

```bash
python coal_conveyor_web.py
```

## 输出路径

- 一体化程序回测模式：`output/conveyor_forecast.html`（由 `coal_conveyor/config.py` 中 `PLOT_SAVE_PATH` 配置）
- `scripts/predict_traffic.py`：`output/forecast_result.html`

若 `output/` 不存在，保存图表前会自动创建。

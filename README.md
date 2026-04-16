# TLM: 煤流输送仿真与智能调速决策系统

> **Traffic & Logistics Management for Coal Conveyor Systems**

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Framework: Flask](https://img.shields.io/badge/Framework-Flask-lightgrey.svg)](https://flask.palletsprojects.com/)

TLM 是一个专为煤矿胶带输送线设计的**集约化节能调速系统**，集成实时物理建模仿真、深度学习流量预测与离散 PID 控制策略，通过精准调速实现皮带机节能降耗。

---

## 核心特性

- **双引擎流量预测**: 支持 **Google TimesFM 2.5**（默认）与 **Amazon Chronos-2**（可选）两种时序预测后端，支持速度协变量增强预测。
- **离散 PID 调速**: 前馈 + 反馈复合控制，内置中点滞回与驻留约束，防止频繁换挡。
- **双工况仿真**: 同一入流下并行运行智能调速与额定带速两条仿真，实时对比累计能耗。
- **实时看板**: Flask Web 后端，实时展示三级皮带载荷分布、工作面落煤流量与预测、带速曲线及节能指标。

---

## 目录结构

| 路径 | 说明 |
| :--- | :--- |
| `run_web.py` | **主启动程序** — 同时开启仿真、预测与 Web 服务 |
| `src/core/` | **核心模块** — 配置 (`config`)、PID 算法 (`pid`)、仿真逻辑 (`simulator`)、状态快照 (`state`)、数据解析 (`data`) |
| `src/predict/` | **预测中心** — TimesFM / Chronos 双后端推理接口 |
| `src/web/` | **交互层** — Flask API、CLI 启动器、实时回放 (`replay`)、前端模板与静态资源 |
| `data/` | 原始流量日志 (`.txt`)，由物理设备采集 |
| `models/` | 预训练模型权重（本地加载） |
| `docs/` | 详细设计文档，含 [速度控制策略](docs/SPEED_CONTROL.md) |
| `requirements-timesfm.txt` | **可选** TimesFM 后端源码安装说明 |

---

## 安装与运行

### 环境要求

- **Python**: 3.10 ~ 3.12
- **操作系统**: Windows / Linux / macOS

### 安装步骤

```bash
# 1. 创建虚拟环境
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\Activate.ps1    # Windows PowerShell

# 2. 克隆仓库并安装依赖
git clone https://github.com/haorumingyue/TLM.git
cd TLM
pip install -r requirements.txt
```

默认 `requirements.txt` 包含 Chronos-2 路线所需依赖。如需启用 TimesFM 后端，请参阅 [requirements-timesfm.txt](requirements-timesfm.txt)。

### 数据与模型

- **流量日志**: 放置于 `data/` 目录，格式为 `<date>.txt`。
- **TimesFM 2.5 模型**（默认）: 从 `models/timesfm-2.5-200m-pytorch/` 加载；支持速度协变量预测。
- **Chronos-2 模型**（可选）: 从 `models/chronos-2/` 加载；若不存在将自动从 HuggingFace 拉取。

### 启动

```bash
python run_web.py
```

浏览器访问 `http://localhost:5173` 进入仪表盘。

---

## 核心配置

关键参数位于 [src/core/config.py](src/core/config.py)。

| 参数 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `PREDICT_BACKEND` | `"timesfm"` | 预测引擎：`timesfm` 或 `chronos` |
| `SPEED_GEARS` | `[1.5, 2.25, 3.0, 3.75, 4.5]` | 各皮带统一 5 档速度 (m/s) |
| `DT` | `1.0` | 仿真步长 (s) |
| `CONTEXT_LENGTH` | `360` | 预测上下文长度（采样点数） |
| `PREDICTION_LENGTH` | `20` | 预测步数 |
| `PORT` | `5173` | Web 服务端口 |

> `L_OPT`（目标填料比，0.60）定义在 `src/core/pid.py` 的 `PIDStrategy` 中，非 WebConfig 配置项。

更多参数与物理含义见 [速度控制策略文档](docs/SPEED_CONTROL.md)。

---

## 文档

| 文档 | 内容 |
| :--- | :--- |
| [速度控制策略](docs/SPEED_CONTROL.md) | 级联布局、PID、换挡、能耗模型、调优 |

---

## 许可证

本项目遵循 [MIT License](LICENSE)，仅供学术研究、仿真演示及技术预览使用。

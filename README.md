# TLM: 煤流输送仿真与智能调速决策系统

> **Traffic & Logistics Management for Coal Conveyor Systems**

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Framework: Flask](https://img.shields.io/badge/Framework-Flask-lightgrey.svg)](https://flask.palletsprojects.com/)

TLM 是一个专为煤矿胶带输送线设计的**集约化节能调速系统**。它集成了**实时物理建模仿真**、**深度学习流量预测**（双模型支持）以及**高稳定性离散 PID 控制策略**，旨在通过精准调速实现皮带机的稳态节能并降低机械磨损。

---

## 核心特性

### 双引擎流量预测

- **多模型支持**: 内置异步推理引擎，支持 **Amazon Chronos-2** 与 **Google Research TimesFM (2.5)** 预训练大模型。
- **动态视野**: 基于最近 60 个采样点的实时滑动窗口，预测未来 10 步的流量分位数分布 (0.1, 0.5, 0.9)，提供决策预见性。

### 稳态离散 PID 调速

- **前馈+反馈机制**: 结合 AI 预测的前馈与实测皮带载荷的闭环反馈。
- **积分优化**: 针对离散档位导致的量子化误差，采用“基于理想连续状态”的积分策略，缓解档位频繁跳动。
- **机械保护**: 内置“中点滞回”与“状态驻留”约束，平衡能效与机械寿命。

### 双工况仿真与节能指标

- **并行对照**: 同一入流时间序列下，同时运行 **智能调速**（`Simulator()`）与 **各带额定带速**（`Simulator(fixed_speed=True)`，`max_speed`）两条仿真。
- **累计电量**: 每条皮带按 `ΔE = P(kW) × Δt(s) / 3600` 积分得到 `energy_kwh`，三条相加为总能耗。
- **看板展示**: **综合节能率**（相对对照组）、**节电 kWh**、**对照累计 kWh**、**智能累计 kWh**。其中“对照/智能累计”均为**累计电量**，不是功率对时间的另一种定义；瞬时总功率另见各时刻 kW 汇总。

定义、公式与解读见 [速度控制文档](docs/SPEED_CONTROL.md) **§6.4 累计能耗与节能指标**。

### 工业级实时看板

- **低延迟仿真**: 基于 Flask 的 Web 后端配合前端可视化，实时同步流量分布、带速档位、瞬时负载及双工况累计能耗曲线。
- **多路数据回放**: 支持加载历史采集日志，模拟多级皮带机的动态煤流叠加效应。

---

## 系统架构

```
历史流量日志 / 实时传感器
        │
        ▼
  ┌─────────────┐    Chronos-2
  │  预测中心    │◄──────────────┐
  │  Predictor   │               │
  └──────┬───────┘    TimesFM    │
         │            ┌──────────┘
         │ 预测前馈   │
         ▼            ▼
  ┌──────────────────────┐
  │    PID 控制器         │
  │  前馈 + 反馈 + 积分   │
  └──────────┬───────────┘
             │ 连续理想带速
             ▼
  ┌──────────────────────┐
  │  离散化 / 滞回策略    │
  │  中点滞回 + 驻留时间   │
  └──────────┬───────────┘
             │ 档位指令
             ▼
  ┌──────────────────────┐
  │  仿真引擎 / 变频驱动   │
  └──────┬─────────┬─────┘
         │         │
         ▼         ▼
    载荷状态    Web Dashboard
```

---

## 目录结构

| 路径 | 说明 |
| :--- | :--- |
| `run_web.py` | **主启动程序** — 同时开启仿真、预测与 Web 服务 |
| `src/core/` | **核心模块** — 配置 (`config`)、PID 算法 (`pid`)、数据解析 (`data`)、仿真逻辑 (`simulator`) |
| `src/predict/` | **预测中心** — 抽象推理接口，支持多后端切换 |
| `src/web/` | **交互层** — API 后端、CLI 工具、前端模板 |
| `data/` | 原始流量日志 (`.txt`)，由物理设备采集 |
| `models/` | 预训练模型权重（本地加载） |
| `docs/` | 详细设计文档，含 [速度控制策略](docs/SPEED_CONTROL.md) |
| `requirements-timesfm.txt` | **可选** TimesFM 后端：源码安装步骤与权重目录说明（不随 `pip install -r requirements.txt` 安装） |

---

## 安装与运行

### 环境要求

- **Python**: 3.10 ~ 3.12
- **操作系统**: Windows / Linux / macOS
- **GPU (可选)**: 如需 GPU 推理，需 NVIDIA 显卡 + CUDA 版 PyTorch

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

默认 **`requirements.txt`** 只包含 **Chronos-2** 路线所需依赖（含 `chronos-forecasting`、`torch` 等）。**TimesFM 不在 PyPI 上以单一包名固定版本**，因此未写入该文件；若启用 TimesFM，请另见 **[requirements-timesfm.txt](requirements-timesfm.txt)** 中的源码安装与权重说明。

### 数据与模型

- **流量日志**: 放置于 `data/` 目录，格式为 `<date>.txt`（如 `data/20250512.txt`）。
- **Chronos-2 模型**: 默认从 `models/chronos-2/` 加载；若不存在，将自动从 HuggingFace 拉取。

### 可选：TimesFM 后端

1. 先完成 `pip install -r requirements.txt`（保证 PyTorch 等与 TLM 一致）。
2. 按 **[requirements-timesfm.txt](requirements-timesfm.txt)** 从官方仓库安装 TimesFM（典型命令如下，**以官方 README 为准**）：

```bash
git clone https://github.com/google-research/timesfm.git
cd timesfm
pip install -e ".[torch]"
```

3. 将 **TimesFM 2.5** 权重放到配置项 `TIMESFM_MODEL_NAME` 指向的目录（默认示例：`models/timesfm-2.5-200m-pytorch/`），下载方式见模型卡或 TimesFM 文档。
4. 在 [src/core/config.py](src/core/config.py) 中设置：

```python
PREDICT_BACKEND = "timesfm"
```

**说明**: TimesFM 对 **Python 版本**较敏感（建议 3.10～3.12）。若加载失败，`Predictor` 会 **自动回退到 Chronos-2**（需已安装 `chronos-forecasting`）。更细的参数与行为见 [docs/SPEED_CONTROL.md](docs/SPEED_CONTROL.md) **§7**。

### 启动

```bash
python run_web.py
```

终端输出监听地址后，浏览器访问 `http://localhost:5173` 进入仪表盘。

---

## 核心配置

关键参数位于 [src/core/config.py](src/core/config.py)；PID 目标填料比位于 [src/core/pid.py](src/core/pid.py)。

| 参数 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `PREDICT_BACKEND` | `"chronos"` | 预测引擎：`chronos` 或 `timesfm` |
| `SPEED_GEARS_MAIN` 等 | `1.5 … 4.5` (5 档) | 各皮带离散速度档位 (m/s)，三条带一致 |
| `L_OPT` | `0.60` | 目标填料比（0~1），见 `PIDStrategy` |
| `cell_length` | `1.0` m | 仿真网格：1 m/格 |
| `BELT_DOWNSAMPLE` | `25` | 主运沿程图 API 每 N 格取 1 点，减轻前端负担（仿真仍为 1 m/格） |
| `LOG_INTERVAL_SEC` | `3.0` | 日志采样间隔 (s) |
| `DT` | `1.0` | 仿真步长 (s) |
| `PORT` | `5173` | Web 服务端口 |

更多参数与物理含义见 [速度控制策略文档](docs/SPEED_CONTROL.md)。

---

## 文档

| 文档 | 内容 |
| :--- | :--- |
| [速度控制策略](docs/SPEED_CONTROL.md) | 级联布局、PID、换挡、能耗模型、**累计能耗与节能指标**、调优 |

---

## 许可证

本项目遵循 [MIT License](LICENSE)，仅供学术研究、仿真演示及技术预览使用。

# 速度控制策略文档

## 1. 概述

本系统采用**三条皮带级联仿真**（主运 → 斜井 → 101），结合 **PID 前馈-反馈控制**与**离散档位换挡**策略，根据入流动态调整各皮带带速，实现节能降耗与防堵保护。

### 1.1 皮带级联布局

```
3306综采(A) ──→ ┌──────────────┐
                │  主运大巷皮带  │ ──→ ┌──────────────┐
3217综采(B) ──→ │  5000m,水平   │     │  主斜井皮带   │ ──→ ┌────────┐
                └──────────────┘     │  1160m,提升340m│     │ 101皮带│
                                     └──────────────┘     │  147m  │
                                                          └────────┘
                                                              ↓
                                                          最终排出
```

每个转载点设有**队列缓冲区**：煤从上游皮带出流后进入下游队列，再按给料机能力装载到下游皮带。A/B 队列由外部日志数据驱动，C 队列由主运出流填充，T_B2_B3 由斜井出流填充。

### 1.2 设计哲学

1. **离散档位控制**：各皮带统一 **5 档**速度（见 §2），通过死区滞回防止频繁换挡。
2. **前馈-反馈复合控制**：前馈基于入流推算目标速度，反馈基于填料比修正。
3. **非对称响应**：升档即时（安全优先），降档延迟（避免反复升降）。
4. **物理能耗模型**：基于阻力、提升高度、辅助功率的功率计算，并对时间积分得到累计电量 (kWh)。

---

## 2. 各皮带物理参数

配置文件：[config.py](../src/core/config.py)

| 参数 | 主运大巷 | 主斜井 | 101皮带 |
|------|---------|--------|---------|
| 长度 | 5000 m | 1160 m | 147 m |
| 格元长度 | **1 m** | **1 m** | **1 m** |
| 速度范围 | 1.5 ~ 4.5 m/s | 同左 | 同左 |
| 最大线密度 | 0.125 t/m | 0.111 t/m | 0.123 t/m |
| 空载线质量 | 78 kg/m | 72 kg/m | 55 kg/m |
| 阻力系数 | 0.032 | 0.034 | 0.035 |
| 驱动效率 | 0.92 | 0.90 | 0.91 |
| 提升高度 | 0 m | 340 m | 0 m |
| 辅助功率 | 16 kW | 12 kW | 4 kW |

仿真按 **1 m/格** 划分网格；主运沿程图向浏览器推送时可经 `BELT_DOWNSAMPLE` 降采样（仅影响绘图点数，不改变仿真步进）。

### 调速档位

三条皮带共用同一组档位（`SPEED_GEARS_MAIN` / `INCLINE` / `PANEL101` 数值一致）：

| 档位 | 1 | 2 | 3 | 4 | 5 |
|------|---|---|---|---|---|
| 速度 (m/s) | 1.5 | 2.25 | 3.0 | 3.75 | 4.5 |

---

## 3. 调速策略架构

实现：[simulator.py](../src/core/simulator.py)

### 3.1 主运皮带 — PID + 前馈预测

接收两路工作面（A/B）入流，使用 `PIDStrategy` 计算连续目标速度，经 `_apply_gears` 映射到离散档位。同时接收 Chronos-2（或 TimesFM）预测的未来流量作为前馈。

### 3.2 斜井皮带 — PID（无前馈）

入流来自主运出流（经 C 队列转载），使用独立 `PIDStrategy` 实例。因主运出流有传输延迟，A/B 预测值不直接用于斜井前馈，斜井 PID 仅用当前出流相关量。

### 3.3 101 皮带 — PID + 档位

当前 Web 仿真中 **三条皮带在智能模式下均使用 `PIDStrategy` + `_apply_gears`**，带速范围与档位表与主运、斜井一致（见 §2）。不存在单独“按 t/h 查表 + 停机”的分流逻辑；若需与旧版脚本对齐，应以仓库内 `simulator.py` 为准。

---

## 4. PID 控制算法

实现：[pid.py](../src/core/pid.py) `PIDStrategy`

### 4.1 关键参数

| 参数 | 值 | 含义 |
|------|-----|------|
| `V_MIN` | 1.5 m/s | 最低带速 |
| `V_MAX` | 4.5 m/s | 最高带速 |
| `L_OPT` | 0.60 | 目标填料比（0~1），约 60% 格元利用率 |

### 4.2 局部拥堵检测

```python
w = np.linspace(0.2, 1.0, len(belt_load))  # 装料端权重最高
s_max = np.max(belt_load * w)
```

`belt_load` 是各格的**填料比**（0~1），权重从出料端 0.2 线性递增到装料端 1.0。装料端（入料点附近）拥堵风险最高，应优先关注。`s_max` 也是填料比量纲，与 `L_OPT` 直接比较。

### 4.3 前馈控制

```python
# 预测轨迹加权衰减
decay = [1.0 / (1.0 + 0.3 * k) for k in range(len(pred_inflow))]
ref_pred = max(pred_inflow * decay)
ref = max(inflow, ref_pred)

# 推算维持目标填料比所需带速
v_flow = ref / (max_density * L_OPT)
```

- 取当前入流与加权预测的最大值作为参考流量
- 预测步按 `1/(1+0.3k)` 衰减：近端步权重高，远端步递减，避免单一远端尖峰过度驱动
- `v_flow` 公式：`入流 / (线密度上限 × 目标填料比)`，使得在此速度下皮带填料比趋于 `L_OPT`

**示例**：入流 0.22 t/s，主运 max_density=0.125 t/m，L_OPT=0.60  
→ v_flow = 0.22 / (0.125 × 0.60) ≈ **2.93 m/s**

### 4.4 超填响应

当皮带填料比超过 `L_OPT` 时，按线性比例从 `v_flow` 向 `V_MAX` 推高：

```python
if s_max > L_OPT and v_flow < V_MAX:
    excess = (s_max - L_OPT) / L_OPT
    t = min(1.0, excess)
    v_overfill = v_flow + t * (V_MAX - v_flow)
```

- 轻微超填（excess 小）时小幅提升
- excess ≥ 1.0 时推至 V_MAX（全速疏散）
- 当 v_flow 已达 V_MAX 时不额外推高

### 4.5 积分与平滑

- **积分项**：消除稳态误差。目标到达时（误差 < 2%），按 `2%/s × dt` 衰减（Anti-windup）
- **低通滤波**：`alpha = dt / (2.0 + dt)`，一阶惯性平滑
- **变化率限制**：±0.15 m/s per step，防止机械冲击

---

## 5. 换挡逻辑

实现：[simulator.py](../src/core/simulator.py) `_apply_gears`

### 5.1 死区滞回

以相邻两档中点为例（如 2.25 与 3.0 m/s 之间）：

```
    2.25      2.5875   3.0     2.6625      3.75
     |----------|--------|---------|-----------|
            降档阈值   当前档    升档阈值
           (中点-0.05)          (中点+0.05)
```

- **升档阈值** = 相邻档中点 + **0.05 m/s**（死区偏移）
- **降档阈值** = 相邻档中点 − **0.05 m/s**
- 死区 0.05 m/s 防止 `v_cont` 在中点附近反复触发升降档

### 5.2 非对称驻留

| 操作 | 驻留要求 | 原因 |
|------|---------|------|
| 升档 | 无（即时） | 流量突增时快速升速防堵 |
| 降档 | 30 s | 等待确认流量确实下降 |

升档后驻留计时器重置，降档需重新等待 30 s。

---

## 6. 物理能耗模型

### 6.1 功率计算

```
P_total = P_auxiliary + P_motion + P_lift
```

| 分量 | 公式 | 说明 |
|------|------|------|
| 辅助功率 | `aux_kw` (常量) | 驱动站空载运行 |
| 运动功率 | `C_res × (m_empty + m_coal) × g × v / η / 1000` | 克服摩擦和滚动阻力 |
| 提升功率 | `Q_kgps × g × H / η / 1000` | 物料提升功率（仅斜井，340 m） |

空载皮带时运动功率最小（仅克服皮带自重摩擦），满载时显著增加。**提升功率仅与瞬时质量流量有关，与带速无关**；斜井在相同出力 (t/h) 下，智能与对照的提升分项往往接近。辅助功率三条带恒定为 16+12+4 kW，不随调速变化。

### 6.2 磨损模型

```
W = W_speed × v² × dt/10 + W_load × Q × v × dt/3600 + W_ramp × |a| × dt
```

- 速度磨损：与速度平方成正比
- 负载磨损：与流量-速度交互成正比
- 加速度磨损：与换挡加速度成正比（换挡越频繁磨损越大）

### 6.3 节能原理（运动项）

入流下降时降速运行：

- 运动功率随速度变化（并与带上存煤量耦合）
- PID 试图将填料比维持在 `L_OPT` 附近
- 辅助功率恒定；**可随调速明显变化的主要为运动功率**；提升功率在出力相近时差异有限

### 6.4 累计能耗与节能指标

**单条皮带累计电量**

每仿真步：

\[
\Delta E_{\mathrm{belt}} = P_{\mathrm{kW}} \times \frac{\Delta t}{3600}
\]

单位 kWh；从仿真开始累加得到 `energy_kwh`。

**智能工况总能耗**

\[
E_{\mathrm{AI}} = \sum_{\mathrm{三条带}} \mathrm{energy\_kwh}
\]

（代码中为 `sim.energy_acc`。）

**对照工况总能耗**

第二台仿真器 `Simulator(fixed_speed=True)`：每步各带强制为配置中的 **`max_speed`（额定带速）**。两工作面 **A/B 的入流速率**由 `Replay.update(sim.time)` 在**同一仿真时刻**写入智能仿真与对照仿真（`replay.py` 中 `_set_lane_rate_both`），与日志时间轴一致；**C** 为配置中的外部入流字段（日志不直接驱动），每步仍与智能侧 `rates["C"]` 对齐（`runtime.py`）。其累计电量记为 \(E_{\mathrm{const}}\)（`sim_const.energy_acc` / API 字段 `total_energy_baseline_kwh`）。

**综合节能率（%）**

\[
\eta = \max\left(0,\ \frac{E_{\mathrm{const}} - E_{\mathrm{AI}}}{E_{\mathrm{const}}} \times 100\right)
\]

当智能侧电耗高于对照时，**节能率钳为 0**（不显示负值节电）。

**节电量 (kWh)**

\[
\Delta E = \max(0,\ E_{\mathrm{const}} - E_{\mathrm{AI}})
\]

（API：`saving_kwh`。）

看板副标题中的 **「对照累计」「智能累计」均指累计电量 kWh**，不是“功率的累计”或另一种功率定义；**瞬时总功率**为当前步各带 `last_power_kw` 之和（kW）。

### 6.5 双机对照的可比性说明

两条仿真**共享同一入流速率时间序列**，但**带速策略不同**，导致转载队列与带面存煤状态会**分叉**。因此 \(E_{\mathrm{const}}\) 与 \(E_{\mathrm{AI}}\) 的差值反映的是「同一日志驱动、不同控制律」下的累计电耗对比，**不是**严格意义上的「完成完全相同吨公里任务」时的单位能耗差。若需工程考核，可结合累计排出量等做 **kWh/t** 类归一化（需另行定义与实现）。

### 6.6 为何综合节能率可能只有几个百分点

常见原因包括：

- **提升 + 辅助**占总能耗比例高：提升项在出力相近时两边接近；辅助为常数项，拉低“可省部分”占总能耗的比例。
- **高流量时段** PID 目标带速接近 **上限**，智能工况与「全程额定」的累计 kWh 差距缩小。
- **运动项**中降速省功率与存煤增阻可能部分抵消。

---

## 7. 预测集成

系统支持两种时序预测后端：**Chronos-2**（默认依赖）与 **Google TimesFM 2.5**（可选源码安装）。切换项为 [config.py](../src/core/config.py) 中的 `PREDICT_BACKEND`（`"chronos"` / `"timesfm"`）。

### 7.1 Chronos-2（默认）

- **Python 包**：`chronos-forecasting`（见仓库根目录 `requirements.txt`）。
- **权重目录**：`WebConfig.MODEL_DIR`（默认 `models/chronos-2/`）。
- **实现**：[predictor.py](../src/predict/predictor.py) `_load_chronos` / `predict` 中 `Chronos2Pipeline.predict_quantiles`。

### 7.2 TimesFM（可选）

TimesFM **未**列入 `requirements.txt`：官方通过 **GitHub 源码 + 可编辑安装** 分发，版本与 extras 以 [google-research/timesfm](https://github.com/google-research/timesfm) 为准。

**推荐步骤**（与 [requirements-timesfm.txt](../requirements-timesfm.txt) 一致）：

1. 在同一虚拟环境中执行 `pip install -r requirements.txt`（含 `torch`）。
2. 克隆 TimesFM 并安装，例如：
   ```bash
   git clone https://github.com/google-research/timesfm.git
   cd timesfm
   pip install -e ".[torch]"
   ```
3. 将 **TimesFM 2.5 PyTorch** 权重放到 `WebConfig.TIMESFM_MODEL_NAME` 指向的本地路径（默认如 `models/timesfm-2.5-200m-pytorch`），以便 `TimesFM_2p5_200M_torch.from_pretrained` 类调用能加载。
4. 设置 `PREDICT_BACKEND = "timesfm"`。

**兼容性与回退**：建议 Python **3.10～3.12**。若 `import timesfm` 或模型加载失败，[predictor.py](../src/predict/predictor.py) `load()` 会打印警告并 **回退到 Chronos-2**（需已安装 `chronos-forecasting`）。

### 7.3 推理与主运前馈（两后端共用）

- **触发**：按日志节拍，`Replay` 将最近 60 个采样点送入预测器
- **输出**：未来 10 步流量，含 0.1/0.5/0.9 分位数
- **融合**：仅主运 PID 使用预测前馈（斜井因传输延迟不使用 A/B 预测）
- **加权**：预测轨迹按 `1/(1+0.3k)` 衰减，取加权最大值

---

## 8. 调优指南

| 参数 | 位置 | 默认值 | 作用 |
|------|------|--------|------|
| `SPEED_GEARS_*` | config.py | 1.5~4.5 五档 | 各皮带离散速度 |
| `L_OPT` | pid.py | 0.60 | 目标填料比，增大更节能但增拥堵风险 |
| `min_dwell_down` | simulator.py | 30 s | 降档驻留，增大减少换挡但降响应 |
| `dead_band` | simulator.py | 0.05 m/s | 换挡死区，增大减少振荡 |
| `DT` | config.py | 1.0 s | 仿真步长 |
| `cell_length` | config.py | 1.0 m | 网格分辨率 |
| `BELT_DOWNSAMPLE` | config.py | 25 | 主运沿程图降采样步长（格） |
| `CONTEXT_LENGTH` | config.py | 60 | 预测上下文长度 |
| `PREDICTION_LENGTH` | config.py | 10 | 预测步数 |
| `PREDICT_BACKEND` | config.py | `chronos` | `chronos` 或 `timesfm`；TimesFM 见 §7.2 与 `requirements-timesfm.txt` |
| `TIMESFM_MODEL_NAME` | config.py | 本地路径 | TimesFM 权重目录，仅 `timesfm` 后端使用 |

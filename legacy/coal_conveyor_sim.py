"""
主煤流输送系统仿真程序
========================
模拟一条5000m主运皮带，带有两个汇入点(0m和1000m)，
实时仿真煤炭在皮带上的负载分布。

"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.widgets import Slider, Button, TextBox
import warnings
import colorama
from colorama import Fore, Style
from abc import ABC, abstractmethod
warnings.filterwarnings("ignore")
colorama.init(autoreset=True)

# 设置中文字体，解决中文乱码问题
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']  # 用来正常显示中文标签
plt.rcParams['axes.unicode_minus'] = False  # 用来正常显示负号

# ============================================================
# 配置参数
# ============================================================
class Config:
    # 皮带参数
    BELT_LENGTH = 5000          # 皮带长度 (m)
    BELT_SPEED  = 4.5          # 皮带速度 (m/s)
    CELL_SIZE   = 1.0          # 每个网格单元长度 (m)

    # 仿真参数
    DT = 0.1                   # 时间步长 (s)
    FPS = 15                   # 动画帧率
    SIM_SPEED = 100            # 仿真倍速（1=实时）

    # 汇入点 (m)
    INFLOW_POSITIONS = [0, 1000]

    # 初始汇入流量 (t/s)
    INITIAL_INFLOW_RATES = [0.05, 0.03]


# ============================================================
# 调速策略接口与实现
# ============================================================
class SpeedControlStrategy(ABC):
    @abstractmethod
    def calculate_speed(self, current_speed: float, current_inflow: float, max_load: float, dt: float, cell_size: float, belt_load: np.ndarray = None) -> float:
        """
        计算下一时刻的目标带速
        :param belt_load: 完整皮带载荷数组，供需要空间感知的策略使用
        """
        pass

class DefaultVFDSpeedControlStrategy(SpeedControlStrategy):
    """默认的智能调速策略(前馈+反馈)"""
    def calculate_speed(self, current_speed: float, current_inflow: float, max_load: float, dt: float, cell_size: float, belt_load: np.ndarray = None) -> float:
        target_load_per_cell = 0.150  # 理想最优单位载荷(t/格，即150kg/m)
        # 前馈计算
        expected_load = (current_inflow * cell_size) / max(1.5, current_speed)
        effective_load = max(max_load, expected_load)

        target_v = max(1.5, min(4.5, (effective_load / target_load_per_cell) * 4.5))
        max_accel = 0.15 * dt
        
        new_speed = current_speed
        if target_v > current_speed + 0.01:
            new_speed = min(target_v, current_speed + max_accel)
        elif target_v < current_speed - 0.01:
            new_speed = max(target_v, current_speed - max_accel)
            
        return new_speed


class AdvancedSpeedControlStrategy(SpeedControlStrategy):
    """
    进阶智能调速策略：引入死区(Deadband)和历史平滑(低通滤波)
    """
    def __init__(self):
        self.target_load_per_cell = 0.150  # 理想最优单位载荷(t/格，即150kg/m)
        self.deadband = 0.05               # 5% 的容忍死区
        self.filtered_target_v = 4.5       # 用于平滑目标速度，初始默认最高速

    def calculate_speed(self, current_speed: float, current_inflow: float, max_load: float, dt: float, cell_size: float, belt_load: np.ndarray = None) -> float:
        # 1. 前馈 + 反馈取最大值作为参考载荷
        expected_load = (current_inflow * cell_size) / max(1.5, current_speed)
        effective_load = max(max_load, expected_load)
        
        # 2. 计算绝对理想速度
        ideal_v = (effective_load / self.target_load_per_cell) * 4.5
        ideal_v = max(1.5, min(4.5, ideal_v))  # 限制在 1.5m/s ~ 4.5m/s 范围内
        
        # 3. 死区过滤：如果理想速度与当前速度差异小于5%（且没有超载风险），拒绝微小的速度波动指令
        diff_ratio = abs(ideal_v - current_speed) / current_speed if current_speed > 0 else 0
        if diff_ratio < self.deadband and effective_load < self.target_load_per_cell * 1.1:
            raw_target_v = current_speed
        else:
            raw_target_v = ideal_v
            
        # 4. 目标速度一阶低通滤波 (时间常数约等于 2 秒，消除尖刺噪音)
        alpha = dt / (2.0 + dt)  
        self.filtered_target_v = self.filtered_target_v * (1 - alpha) + raw_target_v * alpha
        
        # 5. 执行基于最大加速度的平滑限制
        max_accel = 0.15 * dt  # 硬件允许的最大加速度 0.15 m/s^2
        new_speed = current_speed
        
        if self.filtered_target_v > current_speed + 0.005:
            new_speed = min(self.filtered_target_v, current_speed + max_accel)
        elif self.filtered_target_v < current_speed - 0.005:
            new_speed = max(self.filtered_target_v, current_speed - max_accel)
            
        return new_speed


class PIDSpeedControlStrategy(SpeedControlStrategy):
    """
    PID增强调速策略：在进阶策略基础上新增以下改进：
    1. 空间加权有效载荷：靠近卸煤端的煤权重低，避免即将卸落的煤触发无效加速
    2. PID积分项：消除稳态误差，让带速在稳定工况下更精准
    3. 超载保护模式：当载荷超过额定1.5倍时，强制全速清煤，保障设备安全
    """
    V_MIN = 1.5     # 最低带速 (m/s)
    V_MAX = 4.5     # 最高带速 (m/s)
    L_OPT = 0.150   # 理想单位载荷 (t/格)

    def __init__(self, kp: float = 1.0, ki: float = 0.05, deadband: float = 0.05, lpf_tau: float = 2.0, max_accel: float = 0.15):
        """
        :param kp:       比例系数
        :param ki:       积分系数（过大会引起超调，建议 0.02~0.1）
        :param deadband: 死区阈值（速度误差相对比例，默认5%）
        :param lpf_tau:  低通滤波时间常数 (s)，越大越平滑
        :param max_accel: 最大加速度 (m/s²)
        """
        self.kp = kp
        self.ki = ki
        self.deadband = deadband
        self.lpf_tau = lpf_tau
        self.max_accel = max_accel

        self._integral = 0.0        # PID积分累积项
        self._filtered_v = self.V_MAX  # 低通滤波状态
        self._integral_limit = 0.5  # 积分抗饱和限幅 (m/s)

    def calculate_speed(self, current_speed: float, current_inflow: float, max_load: float, dt: float, cell_size: float, belt_load: np.ndarray = None) -> float:
        # ── 1. 空间加权有效载荷 ──────────────────────────────────────
        # 位置越靠近卸煤端（高索引），权重越低，避免快卸完的煤触发加速
        if belt_load is not None and len(belt_load) > 0:
            n = len(belt_load)
            weights = np.linspace(1.0, 0.2, n)   # 入煤端权重1.0 → 卸煤端权重0.2
            weighted_load = belt_load * weights
            spatial_max_load = float(np.max(weighted_load))
        else:
            spatial_max_load = max_load

        # ── 2. 超载保护：货物超过额定1.5倍，强制全速清煤 ────────────
        if spatial_max_load > self.L_OPT * 1.5:
            # 强制全速，跳过所有滤波
            new_speed = min(self.V_MAX, current_speed + self.max_accel * dt)
            self._filtered_v = new_speed   # 同步滤波器状态，防止解除后抖动
            self._integral = 0.0           # 清空积分，防止超调
            return new_speed

        # ── 3. 前馈计算理想速度 ──────────────────────────────────────
        expected_load = (current_inflow * cell_size) / max(self.V_MIN, current_speed)
        effective_load = max(spatial_max_load, expected_load)
        ideal_v_raw = (effective_load / self.L_OPT) * self.V_MAX
        ideal_v = max(self.V_MIN, min(self.V_MAX, ideal_v_raw))

        # ── 4. 死区过滤 ──────────────────────────────────────────────
        diff_ratio = abs(ideal_v - current_speed) / max(current_speed, 1e-6)
        overload_risk = effective_load > self.L_OPT * 1.1
        if diff_ratio < self.deadband and not overload_risk:
            raw_target_v = current_speed
            # 死区内停止积分，防止积分漂移
            self._integral *= 0.98
        else:
            # ── 5. PID积分修正（消除稳态误差）────────────────────────
            error = ideal_v - current_speed
            self._integral += self.ki * error * dt
            # 抗积分饱和限幅
            self._integral = max(-self._integral_limit, min(self._integral_limit, self._integral))
            raw_target_v = max(self.V_MIN, min(self.V_MAX, ideal_v + self._integral))

        # ── 6. 一阶低通滤波（平滑速度指令，去除噪声尖刺） ────────────
        alpha = dt / (self.lpf_tau + dt)
        self._filtered_v = self._filtered_v * (1 - alpha) + raw_target_v * alpha

        # ── 7. 加速度限幅（机械硬约束） ──────────────────────────────
        delta_v_max = self.max_accel * dt
        new_speed = current_speed
        if self._filtered_v > current_speed + 0.005:
            new_speed = min(self._filtered_v, current_speed + delta_v_max)
        elif self._filtered_v < current_speed - 0.005:
            new_speed = max(self._filtered_v, current_speed - delta_v_max)

        return new_speed


# ============================================================
# 主仿真类
# ============================================================
class CoalConveyorSimulator:
    def __init__(self, cfg: type[Config] = Config):
        self.cfg = cfg
        self.n_cells = int(cfg.BELT_LENGTH / cfg.CELL_SIZE)

        # 皮带负载分布 (t)，每个格子存储该位置的煤炭质量
        self.belt_load = np.zeros(self.n_cells)

        # 时间
        self.time = 0.0  # 秒
        self.total_steps = 0

        # 汇入流量历史 (用于显示)
        self.inflow_history = {pos: [] for pos in cfg.INFLOW_POSITIONS}
        self.time_history = []
        self.history = {
            "total_in": [],
            "total_out": [],
            "total_coal": []
        }

        # 累计流量统计
        self.total_inflow = {pos: 0.0 for pos in cfg.INFLOW_POSITIONS}
        self.total_discharge = 0.0

        # 流入点index
        self.inflow_cells = [
            min(int(pos / cfg.CELL_SIZE), self.n_cells - 1)
            for pos in cfg.INFLOW_POSITIONS
        ]

        # 当前流量配置
        self.current_inflow_rates = list(cfg.INITIAL_INFLOW_RATES)

        # 每个时间步注入的质量 (t/step = t/s * dt)
        self.step_inflow = [
            rate * cfg.DT for rate in self.current_inflow_rates
        ]

        # 统计
        self.stats = {
            "max_load": 0.0,
            "avg_load": 0.0,
            "total_coal": 0.0,
        }
        self.fractional_shift_acc = 0.0  # 累计皮带移动的小数部分格子数
        self.belt_speed = cfg.BELT_SPEED # 当前带速
        self.auto_speed = True           # 变频智能调速开关
        self.speed_strategy = PIDSpeedControlStrategy()      # PID增强变频调速策略

    def step(self):
        """执行一个仿真时间步"""
        cfg = self.cfg

        # 1. 汇入点注入煤炭
        for i, cell_idx in enumerate(self.inflow_cells):
            inflow_t = self.step_inflow[i]
            self.belt_load[cell_idx] += inflow_t
            self.total_inflow[cfg.INFLOW_POSITIONS[i]] += inflow_t

        # 2. 皮带传输：所有煤炭向右移动
        # 计算一个时间步皮带移动的距离对应多少个格子
        shift_cells = self.belt_speed * cfg.DT / cfg.CELL_SIZE
        self.fractional_shift_acc += shift_cells

        if self.fractional_shift_acc >= 1:
            # 整数部分：完整移动
            full_shift = int(self.fractional_shift_acc)
            self.fractional_shift_acc -= full_shift
            
            # 尾部煤炭脱落（到达终点5000m）
            discharged = np.sum(self.belt_load[-full_shift:])
            self.total_discharge += discharged
            # 整体右移
            self.belt_load[full_shift:] = self.belt_load[:-full_shift]
            self.belt_load[:full_shift] = 0

            # 小数部分：弥散
            if self.fractional_shift_acc > 1e-6:
                self._diffuse(self.fractional_shift_acc * 0.1)

        else:
            # 速度较小，不到一个格子时，用弥散模拟少量扩散
            self._diffuse(shift_cells * 0.5)

        # 3. 统计更新
        self.total_steps += 1
        self.time += cfg.DT

        self.stats["total_coal"] = np.sum(self.belt_load)
        self.stats["max_load"] = np.max(self.belt_load)
        self.stats["avg_load"] = np.mean(self.belt_load)

        # --- 4. 煤矿智能调速模块 (前馈+反馈闭环控制) ---
        if self.auto_speed:
            current_inflow = sum(self.current_inflow_rates)
            self.belt_speed = self.speed_strategy.calculate_speed(
                current_speed=self.belt_speed,
                current_inflow=current_inflow,
                max_load=self.stats["max_load"],
                dt=cfg.DT,
                cell_size=cfg.CELL_SIZE,
                belt_load=self.belt_load
            )
        else:
            if self.belt_speed < 4.5:
                self.belt_speed = min(4.5, self.belt_speed + 0.15 * cfg.DT)


        # 记录历史
        if self.total_steps % 10 == 0:
            self.time_history.append(self.time)
            for i, pos in enumerate(cfg.INFLOW_POSITIONS):
                self.inflow_history[pos].append(self.current_inflow_rates[i])
            self.history["total_in"].append(sum(self.total_inflow.values()))
            self.history["total_out"].append(self.total_discharge)
            self.history["total_coal"].append(self.stats["total_coal"])

    def _diffuse(self, amount):
        """弥散：模拟煤炭在皮带上不完全均匀分布"""
        if amount <= 0:
            return
        # 简化的弥散：相邻格子间均匀化
        for _ in range(int(amount * 5)):
            if len(self.belt_load) < 2:
                break
            # 随机选择一对相邻格子交换少量
            i = np.random.randint(0, len(self.belt_load) - 1)
            swap = self.belt_load[i] * 0.05 * amount
            if swap > 1e-9:
                self.belt_load[i] -= swap
                self.belt_load[i + 1] += swap

    def set_inflow_rate(self, idx: int, rate: float):
        """设置某个汇入点的流量 (t/s)"""
        self.current_inflow_rates[idx] = rate
        self.step_inflow[idx] = rate * self.cfg.DT

    def set_speed_strategy(self, strategy: SpeedControlStrategy):
        """设置调速策略"""
        self.speed_strategy = strategy

    def get_position(self) -> np.ndarray:
        """获取皮带位置数组 (m)"""
        return np.arange(self.n_cells) * self.cfg.CELL_SIZE

    def get_summary(self) -> str:
        """获取当前状态摘要"""
        total_in = sum(self.total_inflow.values())
        return (
            f"时间: {self.time:.1f}s | "
            f"带速: {self.belt_speed:.2f}m/s | "
            f"皮带总煤量: {self.stats['total_coal']:.2f}t | "
            f"皮带最大煤量: {self.stats['max_load']:.3f}t | "
            f"累计进煤: {total_in:.2f}t | "
            f"累计出煤: {self.total_discharge:.2f}t"
        )


# ============================================================
# 可视化
# ============================================================
class Visualizer:
    def __init__(self, sim: CoalConveyorSimulator):
        self.sim = sim
        cfg = sim.cfg

        # ---- 窗口布局 ----
        self.fig, self.axs = plt.subplots(3, 1, figsize=(14, 9),
                                           gridspec_kw={"height_ratios": [2, 1, 1]})
        self.fig.suptitle("主煤流输送系统仿真", fontsize=14, fontweight="bold")

        # ---- 上图：皮带负载分布 ----
        self.ax = self.axs[0]
        self.ax.set_xlim(0, cfg.BELT_LENGTH)
        self.ax.set_ylim(0, 0.5)
        self.ax.set_xlabel("皮带位置 (m)")
        self.ax.set_ylabel("煤炭负载 (t/格)")
        self.ax.set_title("主运皮带煤炭负载分布实时视图")
        self.ax.grid(True, alpha=0.3)

        # 标记汇入点
        for pos in cfg.INFLOW_POSITIONS:
            self.ax.axvline(pos, color="green", linestyle="--", linewidth=1.5,
                           label=f"汇入点@{pos}m" if pos == cfg.INFLOW_POSITIONS[0] else None)
        self.ax.axvline(cfg.BELT_LENGTH, color="red", linestyle="--",
                        linewidth=1.5, label="卸煤端")

        positions = sim.get_position()
        (self.line,) = self.ax.plot(positions, sim.belt_load,
                                     color="steelblue", linewidth=0.8)
        self.fill = self.ax.fill_between(positions, sim.belt_load,
                                          alpha=0.3, color="steelblue")

        # 标注汇入点流量
        self.inflow_texts = []
        self.face_names = ["3306综采工作面", "3217综采工作面"]
        for i, pos in enumerate(cfg.INFLOW_POSITIONS):
            txt = self.ax.text(pos + 50, 0.35,
                               f"{self.face_names[i]}@{pos}m\n{sim.current_inflow_rates[i]*1000:.0f} kg/s",
                               fontsize=9, color="darkgreen",
                               bbox=dict(boxstyle="round", facecolor="lightgreen", alpha=0.7))
            self.inflow_texts.append(txt)

        self.ax.legend(loc="upper right")

        # ---- 中图：流量时序 ----
        self.ax_flow = self.axs[1]
        self.ax_flow.set_xlim(0, 300)
        self.ax_flow.set_ylim(0, 0.6)
        self.ax_flow.set_xlabel("时间 (s)")
        self.ax_flow.set_ylabel("流量 (t/s)")
        self.ax_flow.set_title("汇入流量时序")
        self.ax_flow.grid(True, alpha=0.3)

        self.flow_lines = []
        colors = ["#e74c3c", "#3498db"]
        labels = [f"{self.face_names[i]}@{pos}m" for i, pos in enumerate(cfg.INFLOW_POSITIONS)]
        for i, (color, label) in enumerate(zip(colors, labels)):
            line, = self.ax_flow.plot([], [], color=color, linewidth=1.5,
                                       label=label, alpha=0.8)
            self.flow_lines.append(line)
        self.ax_flow.legend(loc="upper right", fontsize=8)

        # ---- 下图：累计进出统计 ----
        self.ax_stat = self.axs[2]
        self.ax_stat.set_xlim(0, 300)
        self.ax_stat.set_ylim(0, 500)
        self.ax_stat.set_xlabel("时间 (s)")
        self.ax_stat.set_ylabel("累计煤量 (t)")
        self.ax_stat.set_title("累计进出煤量统计")
        self.ax_stat.grid(True, alpha=0.3)

        self.stat_lines = []
        stat_colors = ["#27ae60", "#e74c3c", "#f39c12"]
        stat_labels = ["总进煤量", "总出煤量", "皮带存煤"]
        for color, label in zip(stat_colors, stat_labels):
            line, = self.ax_stat.plot([], [], color=color, linewidth=2, label=label)
            self.stat_lines.append(line)
        self.ax_stat.legend(loc="upper left", fontsize=8)

        # 状态文字
        self.status_text = self.fig.text(0.5, 0.01,
                                          "初始化中...", ha="center",
                                          fontsize=10, color="gray")

        plt.tight_layout(rect=[0, 0.03, 1, 0.97])

        # ---- 控制面板 ----
        ax_inflow0 = plt.axes([0.08, 0.91, 0.20, 0.03])
        ax_inflow1 = plt.axes([0.33, 0.91, 0.20, 0.03])
        ax_btn_vfd = plt.axes([0.58, 0.91, 0.12, 0.04])
        ax_btn1 = plt.axes([0.72, 0.91, 0.12, 0.04])
        ax_btn2 = plt.axes([0.86, 0.91, 0.10, 0.04])
        
        self.btn_vfd = Button(ax_btn_vfd, "智能调速: ON", color="#2ecc71", hovercolor="#27ae60")
        self.btn_play = Button(ax_btn1, "暂停/继续", color="#3498db", hovercolor="#2980b9")
        self.btn_reset = Button(ax_btn2, "重置", color="#e74c3c", hovercolor="#c0392b")

        # 滑块标签
        self.slider0 = Slider(ax_inflow0, "3306(kg/s)", 0, 500,
                               valinit=sim.current_inflow_rates[0] * 1000, valstep=1)
        self.slider1 = Slider(ax_inflow1, "3217(kg/s)", 0, 500,
                               valinit=sim.current_inflow_rates[1] * 1000, valstep=1)

        self.slider0.on_changed(self._on_slider0)
        self.slider1.on_changed(self._on_slider1)
        self.btn_vfd.on_clicked(self._on_vfd)
        self.btn_play.on_clicked(self._on_pause)
        self.btn_reset.on_clicked(self._on_reset)

        # 动画
        self.paused = False
        self.ani = animation.FuncAnimation(
            self.fig, self._update, interval=int(1000 / cfg.FPS),
            blit=False, cache_frame_data=False
        )

        plt.show()

    def _update(self, frame):
        """每帧更新"""
        cfg = self.sim.cfg

        # 运行多个仿真步骤
        steps_per_frame = max(1, int(cfg.SIM_SPEED / cfg.FPS * (1 / cfg.DT)))
        for _ in range(steps_per_frame):
            if not self.paused:
                self.sim.step()

        # ---- 上图：负载分布 ----
        load = self.sim.belt_load
        positions = self.sim.get_position()
        self.line.set_data(positions, load)

        # 动态更新 fill_between，以展示被颜色填充的面积
        if hasattr(self, 'fill'):
            self.fill.remove()
        self.fill = self.ax.fill_between(positions, load, alpha=0.3, color="steelblue")

        # 动态Y轴
        max_load = np.max(load)
        if max_load > self.ax.get_ylim()[1] * 0.8:
            self.ax.set_ylim(0, max_load * 1.3)

        # 更新汇入点标注
        for i, txt in enumerate(self.inflow_texts):
            rate = self.sim.current_inflow_rates[i] * 1000
            pos = cfg.INFLOW_POSITIONS[i]
            txt.set_text(f"{self.face_names[i]}@{pos}m\n{rate:.0f} kg/s")

        # ---- 中图：流量时序 ----
        th = self.sim.time_history
        if len(th) > 0:
            t_start = max(0, th[-1] - 300)
            self.ax_flow.set_xlim(t_start, th[-1] + 10)

            for i, line in enumerate(self.flow_lines):
                hist = self.sim.inflow_history[cfg.INFLOW_POSITIONS[i]]
                if len(th) != len(hist):
                    continue
                line.set_data(th, hist)

        # ---- 下图：累计统计 ----
        if len(th) > 0:
            t_start = max(0, th[-1] - 300)
            self.ax_stat.set_xlim(t_start, th[-1] + 10)

            total_in = sum(self.sim.total_inflow.values())
            total_out = self.sim.total_discharge
            on_belt = self.sim.stats["total_coal"]

            hist_in = self.sim.history["total_in"]
            hist_out = self.sim.history["total_out"]
            hist_coal = self.sim.history["total_coal"]

            if len(th) == len(hist_in):
                self.stat_lines[0].set_data(th, hist_in)
                self.stat_lines[1].set_data(th, hist_out)
                self.stat_lines[2].set_data(th, hist_coal)

            # 动态Y轴
            ymax = max(total_in, total_out, on_belt, 10)
            self.ax_stat.set_ylim(0, ymax * 1.2)

        # 状态栏
        self.status_text.set_text(self.sim.get_summary())

        return []

    def _on_slider0(self, val):
        self.sim.set_inflow_rate(0, val / 1000)

    def _on_slider1(self, val):
        self.sim.set_inflow_rate(1, val / 1000)

    def _on_vfd(self, event):
        self.sim.auto_speed = not self.sim.auto_speed
        if self.sim.auto_speed:
            self.btn_vfd.label.set_text("智能调速: ON")
            self.btn_vfd.color = "#2ecc71"
        else:
            self.btn_vfd.label.set_text("智能调速: OFF")
            self.btn_vfd.color = "#95a5a6"
        self.btn_vfd.ax.set_facecolor(self.btn_vfd.color)
        self.fig.canvas.draw_idle()

    def _on_pause(self, event):
        self.paused = not self.paused

    def _on_reset(self, event):
        self.sim.__init__(self.sim.cfg)


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    print(Style.BRIGHT + Fore.CYAN + "=" * 50)
    print(Style.BRIGHT + Fore.YELLOW + "  主煤流输送系统仿真")
    print(Style.BRIGHT + Fore.CYAN + "=" * 50)
    print(Fore.GREEN + f"  皮带长度: {Config.BELT_LENGTH}m")
    print(Fore.GREEN + f"  皮带速度: {Config.BELT_SPEED}m/s")
    print(Fore.GREEN + f"  汇入点:   {Config.INFLOW_POSITIONS}m")
    print(Fore.GREEN + f"  初始流量: {Config.INITIAL_INFLOW_RATES} t/s")
    print(Fore.GREEN + f"  网格大小: {Config.CELL_SIZE}m")
    print(Fore.GREEN + f"  时间步长: {Config.DT}s")
    print(Style.BRIGHT + Fore.CYAN + "=" * 50)

    sim = CoalConveyorSimulator()
    vis = Visualizer(sim)

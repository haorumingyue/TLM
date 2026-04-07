"""皮带离散元仿真：入流推进、出流移位、PID 调速与能耗统计。"""
import numpy as np

from .config import WebConfig
from .pid import PIDStrategy


class Simulator:
    """一维皮带煤流仿真；可选固定额定带速作为对照工况。"""

    def __init__(self, fixed_speed=None):
        cfg = WebConfig
        self.n = int(cfg.BELT_LENGTH / cfg.CELL_SIZE)
        self.bl = np.zeros(self.n)
        self.time = self.total_steps = 0.0
        self.frac = 0.0
        # 实际带速：智能调速时将被量化到离散档位
        self.speed = cfg.ACTUAL_SPEED
        self.fixed_speed = fixed_speed
        self.auto = True
        self.pid = PIDStrategy()
        self.rates = [0.0, 0.0]
        self.step_flow = [0.0, 0.0]
        self.cells = [min(int(p / cfg.CELL_SIZE), self.n - 1) for p in cfg.INFLOW_POSITIONS]
        self.total_in = {p: 0.0 for p in cfg.INFLOW_POSITIONS}
        self.total_out = 0.0
        self.stats = {"max": 0.0, "coal": 0.0}
        self.pred_flows = [None, None]
        self.t_hist = []
        self.spd_hist = []
        self.flow_hist = {p: [] for p in cfg.INFLOW_POSITIONS}
        self.cumin_hist = []
        self.cumout_hist = []
        self.coal_hist = []
        self.energy_acc = 0.0
        self.time_acc = 0.0
        # 离散档位控制：记录当前档位索引与当前档最短驻留时间计时
        self._gear_idx = len(WebConfig.SPEED_GEARS) - 1
        self._gear_dwell = 0.0
        # 记录调速事件，用于离线分析：每一段恒定带速的起止时间与速度值
        # 结构示例：{"t_start":0.0,"t_end":12.3,"speed":4.5}
        self.speed_events = [{"t_start": 0.0, "t_end": None, "speed": self.speed}]

    def set_rate(self, idx, rate):
        self.rates[idx] = rate
        self.step_flow[idx] = rate * WebConfig.DT

    def step(self):
        for i, ci in enumerate(self.cells):
            self.bl[ci] += self.step_flow[i]
            self.total_in[WebConfig.INFLOW_POSITIONS[i]] += self.step_flow[i]

        sh = self.speed * WebConfig.DT / WebConfig.CELL_SIZE
        self.frac += sh
        if self.frac >= 1:
            fs = int(self.frac)
            self.frac -= fs
            self.total_out += float(np.sum(self.bl[-fs:]))
            self.bl[fs:] = self.bl[:-fs]
            self.bl[:fs] = 0.0

        self.total_steps += 1
        self.time += WebConfig.DT
        self.stats["coal"] = float(np.sum(self.bl))
        self.stats["max"] = float(np.max(self.bl))

        prev_speed = self.speed

        if self.fixed_speed is not None:
            # 对照工况：始终保持固定额定带速
            self.speed = self.fixed_speed
        elif self.auto:
            # 智能调速：先由 PID 策略计算“连续理想带速”，再量化到离散档位
            vp = [p for p in self.pred_flows if p is not None]
            pc = np.sum(vp, axis=0) if vp else None
            v_cont = self.pid.calc(
                self.speed,
                sum(self.rates),
                self.stats["max"],
                WebConfig.DT,
                self.bl,
                pc,
            )
            self.speed = self._apply_gears(v_cont)

        # 记录能耗与时间
        # 基于真实的带式输送机功率模型：P = P_empty(与带速成正比) + P_load(与质量流量成正比)
        # 根据工业经验，在最高带速 4.5m/s、满载 4500t/h (1.25t/s) 时，空载带等阻力约占总功率的 40%
        p_empty = 0.4 * (self.speed / WebConfig.ACTUAL_SPEED)
        p_load = 0.6 * (sum(self.rates) / 1.25)
        self.energy_acc += (p_empty + p_load) * WebConfig.DT
        self.time_acc += WebConfig.DT
        # 当前档位驻留时间累积
        self._gear_dwell += WebConfig.DT

        # 记录调速事件：当速度发生变化时，关闭上一段并开启新一段
        if self.speed != prev_speed:
            last = self.speed_events[-1]
            if last["t_end"] is None:
                last["t_end"] = self.time
            self.speed_events.append({"t_start": self.time, "t_end": None, "speed": self.speed})

        if int(self.total_steps) % 10 == 0:
            cfg = WebConfig
            N2 = cfg.N_HISTORY * 2
            self.t_hist.append(self.time)
            self.spd_hist.append(self.speed)
            for i, p in enumerate(WebConfig.INFLOW_POSITIONS):
                self.flow_hist[p].append(self.rates[i])
            self.cumin_hist.append(sum(self.total_in.values()))
            self.cumout_hist.append(self.total_out)
            self.coal_hist.append(self.stats["coal"])
            if len(self.t_hist) > N2:
                self.t_hist = self.t_hist[-N2:]
                self.spd_hist = self.spd_hist[-N2:]
                self.cumin_hist = self.cumin_hist[-N2:]
                self.cumout_hist = self.cumout_hist[-N2:]
                self.coal_hist = self.coal_hist[-N2:]
                for p in WebConfig.INFLOW_POSITIONS:
                    self.flow_hist[p] = self.flow_hist[p][-N2:]

    def get_pos(self):
        return np.arange(self.n) * WebConfig.CELL_SIZE

    def _apply_gears(self, v_cont):
        """
        将连续目标带速 v_cont 映射到离散档位，使用档间中点作为简单滞回，减少频繁换挡。
        """
        gears = WebConfig.SPEED_GEARS
        if not gears:
            return v_cont

        # 初始化档位：如果当前索引非法，则按连续速度选最近一档
        idx = self._gear_idx
        if idx < 0 or idx >= len(gears):
            idx = int(np.argmin([abs(g - v_cont) for g in gears]))

        # 每档最短驻留时间（秒），用于限制降档频率
        min_dwell = 30.0

        # 上升趋势：若连续目标明显高于当前档，且超过当前档与下一档的中点，则尽快升档（不受驻留时间限制）
        if v_cont > gears[idx] and idx < len(gears) - 1:
            mid_up = 0.5 * (gears[idx] + gears[idx + 1])
            if v_cont >= mid_up:
                idx += 1

        # 下降趋势：若连续目标明显低于当前档，且低于当前档与上一档的中点，且当前档已驻留足够长时间，则允许降档
        if v_cont < gears[idx] and idx > 0 and self._gear_dwell >= min_dwell:
            mid_down = 0.5 * (gears[idx] + gears[idx - 1])
            if v_cont <= mid_down:
                idx -= 1

        # 档位发生变化时重置驻留计时
        if idx != self._gear_idx:
            self._gear_idx = idx
            self._gear_dwell = 0.0

        return gears[idx]

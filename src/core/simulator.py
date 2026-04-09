"""多皮带级联仿真：入流推进、CFL 对流、PID 调速、物理能耗与磨损统计。

三条皮带（主运 → 斜井 → 101）通过转载点队列级联，参照 0756/app.py ConveyorPlant。
"""
import math

import numpy as np

from .config import WebConfig
from .pid import PIDStrategy


G = 9.81


class BeltState:
    """单条皮带的状态：速度、格元煤量、能耗、磨损等。"""

    __slots__ = (
        "cfg", "speed", "command_speed", "cells", "energy_kwh", "wear_index",
        "cumulative_outflow", "last_outflow_tph", "last_power_kw", "last_fill_ratio",
        "t_hist", "spd_hist", "flow_hist", "energy_hist", "coal_hist",
        "cumin_hist", "cumout_hist",
        "_gear_idx", "_gear_dwell",
        "speed_events",
    )

    def __init__(self, cfg):
        self.cfg = cfg
        n = max(1, int(math.ceil(cfg["length"] / cfg["cell_length"])))
        self.speed = cfg["max_speed"]
        self.command_speed = cfg["max_speed"]
        self.cells = np.zeros(n)
        self.energy_kwh = 0.0
        self.wear_index = 0.0
        self.cumulative_outflow = 0.0
        self.last_outflow_tph = 0.0
        self.last_power_kw = cfg["aux_kw"]
        self.last_fill_ratio = 0.0
        # 历史记录
        self.t_hist = []
        self.spd_hist = []
        self.flow_hist = []
        self.energy_hist = []
        self.coal_hist = []
        self.cumin_hist = []
        self.cumout_hist = []
        # 档位
        gears = _gears_for(cfg["id"])
        self._gear_idx = len(gears) - 1
        self._gear_dwell = 0.0
        # 调速事件
        self.speed_events = [{"t_start": 0.0, "t_end": None, "speed": self.speed}]

    @property
    def inventory_t(self):
        return float(self.cells.sum())

    @property
    def max_cell_t(self):
        return float(np.max(self.cells))

    def get_pos(self):
        return np.arange(len(self.cells)) * self.cfg["cell_length"]


def _gears_for(belt_id):
    if belt_id == "main":
        return WebConfig.SPEED_GEARS_MAIN
    if belt_id == "incline":
        return WebConfig.SPEED_GEARS_INCLINE
    return WebConfig.SPEED_GEARS_PANEL101


def _advect_cells(cells, speed, dx, dt, boundary_in=0.0):
    """CFL 稳定迎风差分传导。

    boundary_in: 本步从上游级联进入首格的煤量（t），
                 按 local_cfl 比例参与首格传导（即作为流入而非存量）。
    """
    if speed <= 1e-6:
        return cells.copy(), 0.0
    cfl = speed * dt / dx
    substeps = max(1, int(math.ceil(cfl / 0.95)))
    local_cfl = cfl / substeps
    # 每个子步的边界流入量 = boundary_in * local_cfl（与 CFL 成正比进入）
    # 但 boundary_in 是总量，均分到子步
    bnd_each = boundary_in / substeps
    updated = cells.copy()
    total_outflow = 0.0
    for _ in range(substeps):
        total_outflow += float(local_cfl * updated[-1])
        nxt = updated.copy()
        # 首格：自身煤传导走 cfl 比例，同时接收边界流入（不被 CFL 削减）
        nxt[0] = updated[0] * (1.0 - local_cfl) + bnd_each
        nxt[1:] = updated[1:] * (1.0 - local_cfl) + updated[:-1] * local_cfl
        updated = nxt
    return np.maximum(updated, 0.0), total_outflow


def _calculate_power_kw(cfg, speed, inventory_t, throughput_tph):
    """物理功率模型（来自 0756 _calculate_power_kw）。"""
    empty_mass_kg = cfg["empty_mass_kg_m"] * cfg["length"]
    inventory_kg = inventory_t * 1000.0
    rolling_force = cfg["resistance"] * (empty_mass_kg + inventory_kg) * G
    motion_kw = rolling_force * max(speed, 0.05) / max(cfg["efficiency"], 0.1) / 1000.0
    throughput_kgps = throughput_tph * 1000.0 / 3600.0
    lift_kw = throughput_kgps * G * cfg["lift_m"] / max(cfg["efficiency"], 0.1) / 1000.0
    return cfg["aux_kw"] + motion_kw + lift_kw


def _calculate_wear(cfg, speed, throughput_tph, accel, dt):
    """磨损增量模型（来自 0756 _calculate_wear_increment）。"""
    base = cfg["wear_speed"] * (speed ** 2) * dt / 10.0
    load_term = cfg["wear_load"] * throughput_tph * max(speed, 0.1) * dt / 3600.0
    ramp_term = cfg["wear_ramp"] * abs(accel) * dt
    return base + load_term + ramp_term


def _apply_gears(v_cont, state, min_dwell_down=30.0):
    """将连续目标带速映射到离散档位，升档即时、降档延迟 min_dwell_down 秒。
    升降档使用不同阈值（死区），避免 v_cont 在中点附近反复触发。
    """
    gears = _gears_for(state.cfg["id"])
    if not gears:
        return v_cont
    idx = state._gear_idx
    if idx < 0 or idx >= len(gears):
        idx = int(np.argmin([abs(g - v_cont) for g in gears]))

    dead_band = 0.05  # 死区偏移量 (m/s)

    # 升档：即时，阈值 = 中点 + dead_band
    if v_cont > gears[idx] and idx < len(gears) - 1:
        mid_up = 0.5 * (gears[idx] + gears[idx + 1]) + dead_band
        if v_cont >= mid_up:
            idx += 1

    # 降档：需驻留足够长时间，阈值 = 中点 - dead_band
    if v_cont < gears[idx] and idx > 0 and state._gear_dwell >= min_dwell_down:
        mid_down = 0.5 * (gears[idx] + gears[idx - 1]) - dead_band
        if v_cont <= mid_down:
            idx -= 1

    if idx != state._gear_idx:
        state._gear_idx = idx
        state._gear_dwell = 0.0

    return gears[idx]



class Simulator:
    """三条皮带级联仿真（主运 → 斜井 → 101），支持智能调速与固定额定速度对照。"""

    def __init__(self, fixed_speed=None):
        self.fixed_speed = fixed_speed  # None=智能调速, "nominal"=各皮带额定速度, 数值=全皮带统一速度
        self.auto = True
        self.time = 0.0
        self.total_steps = 0.0
        self.dispatched = 0.0  # 最终排出量

        # 三条皮带
        self.belts = {}
        for belt_id in WebConfig.BELT_ORDER:
            self.belts[belt_id] = BeltState(WebConfig.BELT_CONFIGS[belt_id])

        # 转载点队列（A/B 为工作面入流缓冲，级联直接注入下游皮带首格）
        self.queues = {"A": 0.0, "B": 0.0}

        # 入流速率（t/s），由外部 set_rate 设置
        self.rates = {"A": 0.0, "B": 0.0}

        # PID 控制器（三条皮带各一个）
        self.pid_main = PIDStrategy()
        self.pid_incline = PIDStrategy()
        self.pid_panel101 = PIDStrategy()

        # 预测入流（用于 PID 前馈）
        self.pred_flows = [None, None]  # 对应 A/B 两路

        # 每路入流的流量历史（用于前端工作面图）
        self.flow_hist = {q: [] for q in WebConfig.INFLOW_QUEUES}

        # 全局汇总历史
        self.t_hist = []
        self.spd_hist = []  # 主运速度
        self.cumin_hist = []
        self.cumout_hist = []
        self.coal_hist = []
        self.energy_hist = []
        self.power_hist = []

    def set_rate(self, idx, rate):
        """设置入流速率。idx 0→队列 A，idx 1→队列 B。"""
        queue_id = WebConfig.INFLOW_QUEUES[idx]
        self.rates[queue_id] = rate

    def step(self):
        dt = WebConfig.DT

        # 入流进入转载点队列（rates 单位为 t/s，乘以 dt 得到 t）
        for qid in WebConfig.INFLOW_QUEUES:
            self.queues[qid] += max(0.0, self.rates.get(qid, 0.0)) * dt

        total_power_kw = 0.0

        # ── 拼接三条皮带为一条连续格元数组 ──
        n_main = len(self.belts["main"].cells)
        n_incline = len(self.belts["incline"].cells)
        n_p101 = len(self.belts["panel101"].cells)
        n_total = n_main + n_incline + n_p101

        # 每格对应的皮带 ID 和在皮带内的局部索引
        belt_of_cell = ["main"] * n_main + ["incline"] * n_incline + ["panel101"] * n_p101

        # 拼接的格元数组（只读参考）和各皮带 max_density 数组
        all_cells = np.concatenate([
            self.belts["main"].cells,
            self.belts["incline"].cells,
            self.belts["panel101"].cells,
        ])
        max_dens = np.array(
            [WebConfig.BELT_MAIN["max_density"]] * n_main +
            [WebConfig.BELT_INCLINE["max_density"]] * n_incline +
            [WebConfig.BELT_PANEL101["max_density"]] * n_p101
        )

        # ── 1. A/B 装载到主运 ──
        cells = all_cells.copy()
        for lp in WebConfig.LOAD_POINTS:
            belt_id = lp["belt"]
            if belt_id != "main":
                continue
            q_mass = self.queues.get(lp["queue"], 0.0)
            if q_mass <= 1e-9:
                continue
            idx = int(lp["pos"])
            cell_cap = max(max_dens[idx] - cells[idx], 0.0)
            feeder_cap = lp["max_tph"] * dt / 3600.0
            loaded = min(q_mass, cell_cap, feeder_cap)
            if loaded > 0.0:
                cells[idx] += loaded
                self.queues[lp["queue"]] -= loaded

        # ── 2. 按皮带分别调速 ──
        for belt_id in WebConfig.BELT_ORDER:
            state = self.belts[belt_id]
            cfg = WebConfig.BELT_CONFIGS[belt_id]
            prev_speed = state.speed

            if self.fixed_speed is not None:
                state.speed = cfg["max_speed"]
            elif self.auto:
                pid = {"main": self.pid_main, "incline": self.pid_incline, "panel101": self.pid_panel101}[belt_id]
                # 本皮带在拼接数组中的范围
                if belt_id == "main":
                    seg = cells[:n_main]
                    inflow = sum(self.rates.get(q, 0.0) for q in ("A", "B"))
                    vp = [p for p in self.pred_flows if p is not None]
                    pc = np.sum(vp, axis=0) if vp else None
                elif belt_id == "incline":
                    seg = cells[n_main:n_main+n_incline]
                    inflow = self.belts["main"].last_outflow_tph / 3600.0
                    pc = None
                else:
                    seg = cells[n_main+n_incline:]
                    inflow = self.belts["incline"].last_outflow_tph / 3600.0
                    pc = None
                fill_denom = cfg["max_density"] * cfg["cell_length"]
                s_max = float(np.max(seg)) / max(fill_denom, 1e-6)
                fill_ratios = seg / max(fill_denom, 1e-6)
                v_cont = pid.calc(state.speed, inflow, s_max, dt, fill_ratios, pc,
                                  max_density=cfg["max_density"])
                state.speed = _apply_gears(v_cont, state)

            state.command_speed = state.speed

        # ── 3. 按皮带分别传导（级联处用 boundary_in 直接传递）──
        main_cells = cells[:n_main].copy()
        main_adv, main_out = _advect_cells(main_cells, self.belts["main"].speed, 1.0, dt)

        # main 出流作为 incline 的 boundary_in（不叠加到 cells，作为传导输入）
        inc_cells = cells[n_main:n_main+n_incline].copy()
        inc_adv, inc_out = _advect_cells(inc_cells, self.belts["incline"].speed, 1.0, dt,
                                         boundary_in=main_out)

        # incline 出流作为 panel101 的 boundary_in
        p101_cells = cells[n_main+n_incline:].copy()
        p101_adv, p101_out = _advect_cells(p101_cells, self.belts["panel101"].speed, 1.0, dt,
                                           boundary_in=inc_out)

        # 写回各皮带
        self.belts["main"].cells = main_adv
        self.belts["main"].last_outflow_tph = main_out * 3600.0 / dt
        self.belts["main"].cumulative_outflow += main_out

        self.belts["incline"].cells = inc_adv
        self.belts["incline"].last_outflow_tph = inc_out * 3600.0 / dt
        self.belts["incline"].cumulative_outflow += inc_out

        self.belts["panel101"].cells = p101_adv
        self.belts["panel101"].last_outflow_tph = p101_out * 3600.0 / dt
        self.belts["panel101"].cumulative_outflow += p101_out
        self.dispatched += p101_out

        # ── 4. 功率、磨损、历史 ──
        for belt_id in WebConfig.BELT_ORDER:
            cfg = WebConfig.BELT_CONFIGS[belt_id]
            state = self.belts[belt_id]
            dx = cfg["cell_length"]
            fill_denom = cfg["max_density"] * dx
            state.last_fill_ratio = float(np.max(state.cells / max(fill_denom, 1e-6)))

            power_kw = _calculate_power_kw(cfg, state.speed, state.inventory_t, state.last_outflow_tph)
            state.last_power_kw = power_kw

            accel = 0.0  # 简化：功率计算不需要精确加速度
            wear_inc = _calculate_wear(cfg, state.speed, state.last_outflow_tph, accel, dt)
            state.wear_index += wear_inc

            state.energy_kwh += power_kw * dt / 3600.0
            state._gear_dwell += dt
            total_power_kw += power_kw

        self.total_steps += 1
        self.time += dt

        # 全局历史记录（每 10 步采样）
        if int(self.total_steps) % 10 == 0:
            N2 = WebConfig.N_HISTORY * 2
            main = self.belts["main"]
            self.t_hist.append(self.time)
            self.spd_hist.append(main.speed)
            self.cumin_hist.append(sum(self.queues.get(q, 0.0) for q in WebConfig.INFLOW_QUEUES) + main.inventory_t + self.belts["incline"].inventory_t)
            self.cumout_hist.append(self.dispatched)
            total_coal = sum(b.inventory_t for b in self.belts.values()) + sum(self.queues.values())
            self.coal_hist.append(total_coal)
            total_energy = sum(b.energy_kwh for b in self.belts.values())
            self.energy_hist.append(total_energy)
            self.power_hist.append(total_power_kw)
            for q in WebConfig.INFLOW_QUEUES:
                self.flow_hist[q].append(self.rates.get(q, 0.0))
            if len(self.t_hist) > N2:
                self.t_hist = self.t_hist[-N2:]
                self.spd_hist = self.spd_hist[-N2:]
                self.cumin_hist = self.cumin_hist[-N2:]
                self.cumout_hist = self.cumout_hist[-N2:]
                self.coal_hist = self.coal_hist[-N2:]
                self.energy_hist = self.energy_hist[-N2:]
                self.power_hist = self.power_hist[-N2:]
                for q in WebConfig.INFLOW_QUEUES:
                    self.flow_hist[q] = self.flow_hist[q][-N2:]

    @property
    def speed(self):
        """主运皮带速度（向后兼容）。"""
        return self.belts["main"].speed

    @property
    def energy_acc(self):
        """总能耗 kWh（向后兼容）。"""
        return sum(b.energy_kwh for b in self.belts.values())

    @property
    def time_acc(self):
        return self.time

    @property
    def stats(self):
        total_coal = sum(b.inventory_t for b in self.belts.values()) + sum(self.queues.values())
        return {"coal": total_coal, "max": max(b.max_cell_t / max(b.cfg["max_density"] * b.cfg["cell_length"], 1e-6) for b in self.belts.values())}

    @property
    def total_in(self):
        """各入流点累计入煤量（近似：速率 t/s × 时间 s）。"""
        return {q: self.rates.get(q, 0.0) * self.time for q in WebConfig.INFLOW_QUEUES}

    @property
    def total_out(self):
        return self.dispatched

    def get_pos(self):
        """主运皮带位置数组。"""
        return self.belts["main"].get_pos()


def _panel101_band_speed(demand_tph):
    """101 皮带简单分档（来自 0756 _panel101_band_speed）。"""
    if demand_tph >= 800.0:
        return 2.4
    if demand_tph >= 600.0:
        return 2.0
    if demand_tph >= 400.0:
        return 1.6
    return 1.2

from __future__ import annotations

import argparse
import copy
import math
import sys
from collections import deque
from dataclasses import dataclass
from typing import Callable

import numpy as np
from flask import Flask, jsonify, render_template, request

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

G = 9.81
CONTROL_DT_S = 5.0
HISTORY_LIMIT = 240
BELT_ORDER = ("main", "incline", "panel101")
CONTROLLABLE_BELTS = ("main", "incline", "panel101")
EXTERNAL_QUEUE_IDS = ("A", "B", "C")


@dataclass(frozen=True)
class BeltConfig:
    belt_id: str
    name: str
    length_m: float
    cell_length_m: float
    min_speed_mps: float
    max_speed_mps: float
    nominal_speed_mps: float
    initial_speed_mps: float
    controllable: bool
    max_density_tpm: float
    empty_mass_per_m_kg: float
    resistance_factor: float
    drive_efficiency: float
    lift_height_m: float
    auxiliary_power_kw: float
    wear_speed_coeff: float
    wear_load_coeff: float
    wear_ramp_coeff: float
    discharge_to_queue: str | None = None


@dataclass(frozen=True)
class LoadPointConfig:
    load_id: str
    name: str
    belt_id: str
    position_m: float
    queue_id: str
    feeder_max_tph: float


@dataclass
class ControllerWeights:
    power: float = 1.0
    wear: float = 10.0
    queue: float = 45.0
    fill: float = 200.0
    ramp: float = 8.0


@dataclass
class BeltState:
    speed_mps: float
    command_speed_mps: float
    cells_t: np.ndarray
    energy_kwh: float = 0.0
    wear_index: float = 0.0
    cumulative_outflow_t: float = 0.0
    last_outflow_tph: float = 0.0
    last_loaded_t: float = 0.0
    last_power_kw: float = 0.0
    last_fill_ratio: float = 0.0

    @property
    def inventory_t(self) -> float:
        return float(self.cells_t.sum())


def build_belt_configs() -> dict[str, BeltConfig]:
    # Shared physical/initial parameters are aligned to 煤流协同控制程序.py
    return {
        "main": BeltConfig(
            belt_id="main",
            name="主运大巷皮带",
            length_m=5000.0,
            cell_length_m=25.0,
            min_speed_mps=1.6,
            max_speed_mps=4.0,
            nominal_speed_mps=4.0,
            initial_speed_mps=4.0,
            controllable=True,
            max_density_tpm=0.125,
            empty_mass_per_m_kg=78.0,
            resistance_factor=0.032,
            drive_efficiency=0.92,
            lift_height_m=0.0,
            auxiliary_power_kw=16.0,
            wear_speed_coeff=0.050,
            wear_load_coeff=0.022,
            wear_ramp_coeff=0.80,
        ),
        "incline": BeltConfig(
            belt_id="incline",
            name="主斜井皮带",
            length_m=1160.0,
            cell_length_m=20.0,
            min_speed_mps=1.4,
            max_speed_mps=2.6,
            nominal_speed_mps=2.6,
            initial_speed_mps=4.0,
            controllable=True,
            max_density_tpm=0.111,
            empty_mass_per_m_kg=72.0,
            resistance_factor=0.034,
            drive_efficiency=0.90,
            lift_height_m=340.0,
            auxiliary_power_kw=12.0,
            wear_speed_coeff=0.060,
            wear_load_coeff=0.028,
            wear_ramp_coeff=0.90,
            discharge_to_queue="T_B2_B3",
        ),
        "panel101": BeltConfig(
            belt_id="panel101",
            name="101皮带",
            length_m=147.0,
            cell_length_m=7.0,
            min_speed_mps=1.2,
            max_speed_mps=2.4,
            nominal_speed_mps=2.4,
            initial_speed_mps=2.4,
            controllable=True,
            max_density_tpm=0.123,
            empty_mass_per_m_kg=55.0,
            resistance_factor=0.035,
            drive_efficiency=0.91,
            lift_height_m=0.0,
            auxiliary_power_kw=4.0,
            wear_speed_coeff=0.045,
            wear_load_coeff=0.020,
            wear_ramp_coeff=1.00,
        ),
    }


def build_load_points() -> list[LoadPointConfig]:
    return [
        LoadPointConfig("A", "输入点A", "main", 0.0, "A", 1500.0),
        LoadPointConfig("B", "输入点B", "main", 2500.0, "B", 1200.0),
        LoadPointConfig("C", "输入点C", "incline", 0.0, "C", 900.0),
        LoadPointConfig("T_B2_B3", "斜井到101转载点", "panel101", 0.0, "T_B2_B3", 850.0),
    ]


def build_grids(configs: dict[str, BeltConfig]) -> dict[str, np.ndarray]:
    grids: dict[str, np.ndarray] = {}
    for belt_id in CONTROLLABLE_BELTS:
        cfg = configs[belt_id]
        grids[belt_id] = np.round(
            np.arange(cfg.min_speed_mps, cfg.max_speed_mps + 0.001, 0.2),
            2,
        )
    return grids


class ConveyorPlant:
    def __init__(
        self,
        belt_configs: dict[str, BeltConfig],
        load_points: list[LoadPointConfig],
        ramp_rate_mps_per_s: float = 0.12,
    ) -> None:
        self.belt_configs = belt_configs
        self.load_points = load_points
        self.load_points_by_belt: dict[str, list[LoadPointConfig]] = {belt_id: [] for belt_id in belt_configs}
        for point in load_points:
            self.load_points_by_belt[point.belt_id].append(point)
        self.ramp_rate_mps_per_s = ramp_rate_mps_per_s
        self.reset()

    def reset(self) -> None:
        self.time_s = 0.0
        self.dispatched_t = 0.0
        self.queue_peak_t = 0.0
        self.states: dict[str, BeltState] = {}
        self.queues_t = {queue_id: 0.0 for queue_id in {"A", "B", "C", "T_B2_B3"}}
        for belt_id, cfg in self.belt_configs.items():
            num_cells = max(1, int(math.ceil(cfg.length_m / cfg.cell_length_m)))
            self.states[belt_id] = BeltState(
                speed_mps=cfg.initial_speed_mps,
                command_speed_mps=cfg.initial_speed_mps,
                cells_t=np.zeros(num_cells, dtype=float),
            )

    def clone(self) -> ConveyorPlant:
        return copy.deepcopy(self)

    def _load_index(self, belt_id: str, position_m: float) -> int:
        cfg = self.belt_configs[belt_id]
        idx = int(position_m / cfg.cell_length_m)
        return min(max(idx, 0), len(self.states[belt_id].cells_t) - 1)

    @staticmethod
    def _advect_cells(cells_t: np.ndarray, speed_mps: float, dx_m: float, dt_s: float) -> tuple[np.ndarray, float]:
        if speed_mps <= 1e-6:
            return cells_t.copy(), 0.0
        cfl = speed_mps * dt_s / dx_m
        substeps = max(1, int(math.ceil(cfl / 0.95)))
        local_cfl = cfl / substeps
        updated = cells_t.copy()
        total_outflow_t = 0.0
        for _ in range(substeps):
            next_cells = updated.copy()
            total_outflow_t += float(local_cfl * updated[-1])
            next_cells[0] = updated[0] * (1.0 - local_cfl)
            next_cells[1:] = updated[1:] * (1.0 - local_cfl) + updated[:-1] * local_cfl
            updated = next_cells
        return np.maximum(updated, 0.0), total_outflow_t

    @staticmethod
    def _calculate_power_kw(
        cfg: BeltConfig,
        speed_mps: float,
        inventory_t: float,
        throughput_tph: float,
    ) -> float:
        empty_mass_kg = cfg.empty_mass_per_m_kg * cfg.length_m
        inventory_kg = inventory_t * 1000.0
        rolling_force_n = cfg.resistance_factor * (empty_mass_kg + inventory_kg) * G
        motion_power_kw = rolling_force_n * max(speed_mps, 0.05) / max(cfg.drive_efficiency, 0.1) / 1000.0
        throughput_kgps = throughput_tph * 1000.0 / 3600.0
        lift_power_kw = throughput_kgps * G * cfg.lift_height_m / max(cfg.drive_efficiency, 0.1) / 1000.0
        return cfg.auxiliary_power_kw + motion_power_kw + lift_power_kw

    @staticmethod
    def _calculate_wear_increment(
        cfg: BeltConfig,
        speed_mps: float,
        throughput_tph: float,
        acceleration_mps2: float,
        dt_s: float,
    ) -> float:
        base = cfg.wear_speed_coeff * (speed_mps ** 2) * dt_s / 10.0
        load_term = cfg.wear_load_coeff * throughput_tph * max(speed_mps, 0.1) * dt_s / 3600.0
        ramp_term = cfg.wear_ramp_coeff * abs(acceleration_mps2) * dt_s
        return base + load_term + ramp_term

    def step(
        self,
        commands_mps: dict[str, float],
        inflow_tph: dict[str, float],
        dt_s: float,
        apply_ramp_limit: bool = True,
    ) -> dict[str, float]:
        for queue_id in EXTERNAL_QUEUE_IDS:
            self.queues_t[queue_id] += max(0.0, inflow_tph.get(queue_id, 0.0)) * dt_s / 3600.0
        belt_metrics: dict[str, dict[str, float]] = {}
        total_power_kw = 0.0
        total_wear_increment = 0.0
        for belt_id in BELT_ORDER:
            cfg = self.belt_configs[belt_id]
            state = self.states[belt_id]
            target_speed = commands_mps.get(belt_id, state.command_speed_mps)
            if not cfg.controllable:
                target_speed = cfg.initial_speed_mps
            target_speed = float(np.clip(target_speed, cfg.min_speed_mps, cfg.max_speed_mps))
            previous_speed = state.speed_mps
            if apply_ramp_limit:
                max_delta = self.ramp_rate_mps_per_s * dt_s
                delta = target_speed - previous_speed
                if abs(delta) > max_delta:
                    target_speed = previous_speed + math.copysign(max_delta, delta)
            state.command_speed_mps = float(commands_mps.get(belt_id, target_speed))
            state.speed_mps = float(target_speed)
            acceleration_mps2 = (state.speed_mps - previous_speed) / dt_s
            cells_t = state.cells_t.copy()
            loaded_total_t = 0.0
            feeder_queue_t = 0.0
            for point in self.load_points_by_belt[belt_id]:
                queue_mass_t = self.queues_t.get(point.queue_id, 0.0)
                feeder_queue_t += queue_mass_t
                if queue_mass_t <= 1e-9:
                    continue
                idx = self._load_index(belt_id, point.position_m)
                cell_capacity_t = max(cfg.max_density_tpm * cfg.cell_length_m - cells_t[idx], 0.0)
                feeder_capacity_t = point.feeder_max_tph * dt_s / 3600.0
                loaded_t = min(queue_mass_t, cell_capacity_t, feeder_capacity_t)
                if loaded_t > 0.0:
                    cells_t[idx] += loaded_t
                    self.queues_t[point.queue_id] -= loaded_t
                    loaded_total_t += loaded_t
            advanced_cells_t, outflow_t = self._advect_cells(cells_t, state.speed_mps, cfg.cell_length_m, dt_s)
            state.cells_t = advanced_cells_t
            state.last_loaded_t = loaded_total_t
            state.last_outflow_tph = outflow_t * 3600.0 / dt_s
            state.cumulative_outflow_t += outflow_t
            if cfg.discharge_to_queue:
                self.queues_t[cfg.discharge_to_queue] += outflow_t
            else:
                self.dispatched_t += outflow_t
            fill_denominator = cfg.max_density_tpm * cfg.cell_length_m
            fill_ratio = float(np.max(state.cells_t / max(fill_denominator, 1e-6)))
            state.last_fill_ratio = fill_ratio
            power_kw = self._calculate_power_kw(cfg, state.speed_mps, state.inventory_t, state.last_outflow_tph)
            state.last_power_kw = power_kw
            wear_increment = self._calculate_wear_increment(
                cfg,
                state.speed_mps,
                state.last_outflow_tph,
                acceleration_mps2,
                dt_s,
            )
            state.energy_kwh += power_kw * dt_s / 3600.0
            state.wear_index += wear_increment
            total_power_kw += power_kw
            total_wear_increment += wear_increment
            belt_metrics[belt_id] = {
                "power_kw": power_kw,
                "fill_ratio": fill_ratio,
                "inventory_t": state.inventory_t,
                "outflow_tph": state.last_outflow_tph,
                "feeder_queue_t": feeder_queue_t,
            }
        self.time_s += dt_s
        queue_total_t = float(sum(self.queues_t.values()))
        self.queue_peak_t = max(self.queue_peak_t, queue_total_t)
        return {
            "total_power_kw": total_power_kw,
            "total_wear_increment": total_wear_increment,
            "total_queue_t": queue_total_t,
            "belt_metrics": belt_metrics,
        }

    def total_energy_kwh(self) -> float:
        return float(sum(state.energy_kwh for state in self.states.values()))

    def total_wear_index(self) -> float:
        return float(sum(state.wear_index for state in self.states.values()))


class RuleBandController:
    def __init__(self, delay_s: float = 90.0) -> None:
        self.delay_s = delay_s
        self.pending: dict[str, dict[str, float | None]] = {
            belt_id: {"target": None, "timer_s": 0.0} for belt_id in CONTROLLABLE_BELTS
        }

    def _band_speed(self, belt_id: str, demand_tph: float) -> float:
        if belt_id == "main":
            if demand_tph >= 1400.0:
                return 4.0
            if demand_tph >= 1000.0:
                return 3.2
            if demand_tph >= 600.0:
                return 2.4
            return 1.6
        if belt_id == "incline":
            if demand_tph >= 800.0:
                return 2.6
            if demand_tph >= 600.0:
                return 2.2
            if demand_tph >= 400.0:
                return 1.8
            return 1.4
        if demand_tph >= 800.0:
            return 2.4
        if demand_tph >= 600.0:
            return 2.0
        if demand_tph >= 400.0:
            return 1.6
        return 1.2

    def select_commands(self, plant: ConveyorPlant, inflow_tph: dict[str, float], dt_s: float) -> tuple[dict[str, float], dict[str, float]]:
        queue_main = plant.queues_t["A"] + plant.queues_t["B"]
        queue_incline = plant.queues_t["C"]
        queue_101 = plant.queues_t["T_B2_B3"]
        demand = {
            "main": inflow_tph.get("A", 0.0) + inflow_tph.get("B", 0.0) + queue_main * 60.0,
            "incline": inflow_tph.get("C", 0.0) + queue_incline * 70.0,
            "panel101": plant.states["incline"].last_outflow_tph + queue_101 * 80.0,
        }
        commands: dict[str, float] = {}
        for belt_id in CONTROLLABLE_BELTS:
            state = plant.states[belt_id]
            target = self._band_speed(belt_id, demand[belt_id])
            pending = self.pending[belt_id]
            if target > state.speed_mps + 1e-6:
                pending["target"] = None
                pending["timer_s"] = 0.0
                commands[belt_id] = target
            elif target < state.speed_mps - 1e-6:
                if pending["target"] != target:
                    pending["target"] = target
                    pending["timer_s"] = 0.0
                else:
                    pending["timer_s"] = float(pending["timer_s"]) + dt_s
                commands[belt_id] = state.command_speed_mps if float(pending["timer_s"]) < self.delay_s else target
            else:
                pending["target"] = None
                pending["timer_s"] = 0.0
                commands[belt_id] = target
        return commands, {
            "strategy": "分档延时基线",
            "main_target_mps": commands["main"],
            "incline_target_mps": commands["incline"],
            "panel101_target_mps": commands["panel101"],
            "main_demand_tph": demand["main"],
            "incline_demand_tph": demand["incline"],
            "panel101_demand_tph": demand["panel101"],
        }


class GridMPCController:
    def __init__(
        self,
        belt_configs: dict[str, BeltConfig],
        speed_grids: dict[str, np.ndarray],
        weights: ControllerWeights | None = None,
        horizon_steps: int = 12,
        horizon_dt_s: float = CONTROL_DT_S,
    ) -> None:
        self.belt_configs = belt_configs
        self.speed_grids = speed_grids
        self.weights = weights or ControllerWeights()
        self.horizon_steps = horizon_steps
        self.horizon_dt_s = horizon_dt_s

    def update_weights(self, weights: ControllerWeights) -> None:
        self.weights = weights

    @staticmethod
    def _panel101_band_speed(demand_tph: float) -> float:
        if demand_tph >= 800.0:
            return 2.4
        if demand_tph >= 600.0:
            return 2.0
        if demand_tph >= 400.0:
            return 1.6
        return 1.2

    def select_commands(
        self,
        plant: ConveyorPlant,
        rate_forecaster: Callable[[float], dict[str, float]],
    ) -> tuple[dict[str, float], dict[str, float]]:
        main_state = plant.states["main"]
        incline_state = plant.states["incline"]
        panel101_state = plant.states["panel101"]
        panel101_initial_cmd = self._panel101_band_speed(
            plant.states["incline"].last_outflow_tph + plant.queues_t["T_B2_B3"] * 80.0
        )
        main_range = self.belt_configs["main"].max_speed_mps - self.belt_configs["main"].min_speed_mps
        incline_range = self.belt_configs["incline"].max_speed_mps - self.belt_configs["incline"].min_speed_mps
        panel101_range = self.belt_configs["panel101"].max_speed_mps - self.belt_configs["panel101"].min_speed_mps
        best_cost = float("inf")
        best_commands = {
            "main": main_state.command_speed_mps,
            "incline": incline_state.command_speed_mps,
            "panel101": panel101_state.command_speed_mps,
        }

        for main_cmd in self.speed_grids["main"]:
            for incline_cmd in self.speed_grids["incline"]:
                sim = plant.clone()
                local_cost = 0.0
                initial_ramp_cost = (
                    ((main_cmd - main_state.speed_mps) / max(main_range, 1e-6)) ** 2
                    + ((incline_cmd - incline_state.speed_mps) / max(incline_range, 1e-6)) ** 2
                    + ((panel101_initial_cmd - panel101_state.speed_mps) / max(panel101_range, 1e-6)) ** 2
                )
                local_cost += self.weights.ramp * initial_ramp_cost
                for step_idx in range(self.horizon_steps):
                    future_time_s = sim.time_s
                    inflow_tph = rate_forecaster(future_time_s)
                    panel101_demand_tph = sim.states["incline"].last_outflow_tph + sim.queues_t["T_B2_B3"] * 80.0
                    panel101_cmd = self._panel101_band_speed(panel101_demand_tph)
                    metrics = sim.step(
                        {
                            "main": float(main_cmd),
                            "incline": float(incline_cmd),
                            "panel101": float(panel101_cmd),
                        },
                        inflow_tph,
                        self.horizon_dt_s,
                        apply_ramp_limit=False,
                    )
                    dt_h = self.horizon_dt_s / 3600.0
                    queue_penalty = metrics["total_queue_t"] ** 2
                    fill_penalty = 0.0
                    for belt_metrics in metrics["belt_metrics"].values():
                        fill_penalty += max(0.0, belt_metrics["fill_ratio"] - 0.92) ** 2
                    local_cost += self.weights.power * metrics["total_power_kw"] * dt_h
                    local_cost += self.weights.wear * metrics["total_wear_increment"]
                    local_cost += self.weights.queue * queue_penalty * dt_h
                    local_cost += self.weights.fill * fill_penalty
                if local_cost < best_cost:
                    best_cost = local_cost
                    best_commands = {"main": float(main_cmd), "incline": float(incline_cmd)}

        panel101_demand_tph = plant.states["incline"].last_outflow_tph + plant.queues_t["T_B2_B3"] * 80.0
        best_commands["panel101"] = self._panel101_band_speed(panel101_demand_tph)

        return best_commands, {
            "strategy": "滚动网格MPC",
            "main_target_mps": best_commands["main"],
            "incline_target_mps": best_commands["incline"],
            "panel101_target_mps": best_commands["panel101"],
            "estimated_cost": round(best_cost, 4),
        }


class DashboardEngine:
    def __init__(self) -> None:
        self.belt_configs = build_belt_configs()
        self.load_points = build_load_points()
        self.speed_grids = build_grids(self.belt_configs)
        self.history: deque[dict[str, float]] = deque(maxlen=HISTORY_LIMIT)
        self.mode = "optimized"
        self.scenario = "manual"
        self.running = True
        self.manual_rates_tph = {"A": 200.0, "B": 200.0, "C": 200.0}
        self.weights = ControllerWeights()
        self.optimizer = GridMPCController(self.belt_configs, self.speed_grids, self.weights)
        self.baseline = RuleBandController()
        self.plant = ConveyorPlant(self.belt_configs, self.load_points)
        self.last_diagnostics: dict[str, float | str] = {
            "strategy": "滚动网格MPC",
            "main_target_mps": self.plant.states["main"].command_speed_mps,
            "incline_target_mps": self.plant.states["incline"].command_speed_mps,
            "panel101_target_mps": self.plant.states["panel101"].command_speed_mps,
        }
        self.last_rates_tph = self.manual_rates_tph.copy()
        self.record_history()

    def reset(self) -> None:
        self.history.clear()
        self.baseline = RuleBandController()
        self.optimizer = GridMPCController(self.belt_configs, self.speed_grids, self.weights)
        self.plant = ConveyorPlant(self.belt_configs, self.load_points)
        self.last_diagnostics = {
            "strategy": "滚动网格MPC" if self.mode == "optimized" else "分档延时基线",
            "main_target_mps": self.plant.states["main"].command_speed_mps,
            "incline_target_mps": self.plant.states["incline"].command_speed_mps,
            "panel101_target_mps": self.plant.states["panel101"].command_speed_mps,
        }
        self.last_rates_tph = self.current_inflow_rates(self.plant.time_s)
        self.record_history()

    @staticmethod
    def _clamp_rate(value: float) -> float:
        return float(np.clip(value, 0.0, 1500.0))

    def update_settings(self, payload: dict[str, object]) -> None:
        if "mode" in payload:
            mode = str(payload["mode"])
            if mode in {"optimized", "baseline"}:
                self.mode = mode
        if "scenario" in payload:
            scenario = str(payload["scenario"])
            if scenario in {"manual", "wave", "pulse", "benchmark"}:
                self.scenario = scenario
        if "running" in payload:
            self.running = bool(payload["running"])
        if "manual_rates_tph" in payload and isinstance(payload["manual_rates_tph"], dict):
            next_rates = {}
            for queue_id in EXTERNAL_QUEUE_IDS:
                next_rates[queue_id] = self._clamp_rate(
                    float(payload["manual_rates_tph"].get(queue_id, self.manual_rates_tph[queue_id]))
                )
            self.manual_rates_tph = next_rates
        if "weights" in payload and isinstance(payload["weights"], dict):
            self.weights = ControllerWeights(
                power=float(payload["weights"].get("power", self.weights.power)),
                wear=float(payload["weights"].get("wear", self.weights.wear)),
                queue=float(payload["weights"].get("queue", self.weights.queue)),
                fill=float(payload["weights"].get("fill", self.weights.fill)),
                ramp=float(payload["weights"].get("ramp", self.weights.ramp)),
            )
            self.optimizer.update_weights(self.weights)

    def current_inflow_rates(self, time_s: float) -> dict[str, float]:
        base = self.manual_rates_tph
        if self.scenario == "manual":
            return base.copy()
        if self.scenario == "wave":
            return {
                "A": self._clamp_rate(base["A"] * (0.82 + 0.22 * math.sin(2 * math.pi * time_s / 900.0))),
                "B": self._clamp_rate(base["B"] * (0.90 + 0.18 * math.sin(2 * math.pi * (time_s + 150.0) / 620.0))),
                "C": self._clamp_rate(base["C"] * (0.88 + 0.20 * math.sin(2 * math.pi * (time_s + 240.0) / 760.0))),
            }
        if self.scenario == "pulse":
            burst = 240.0 if 420.0 <= (time_s % 1200.0) <= 660.0 else 0.0
            return {
                "A": self._clamp_rate(base["A"] + burst),
                "B": self._clamp_rate(base["B"] + 80.0 * (1.0 if 760.0 <= (time_s % 1200.0) <= 980.0 else 0.0)),
                "C": self._clamp_rate(base["C"] + 140.0 * (1.0 if 180.0 <= (time_s % 900.0) <= 360.0 else 0.0)),
            }
        cycle = time_s % 1800.0
        return {
            "A": self._clamp_rate(250.0 + 120.0 * max(0.0, math.sin(2 * math.pi * cycle / 1800.0))),
            "B": self._clamp_rate(140.0 + 130.0 * max(0.0, math.sin(2 * math.pi * (cycle + 320.0) / 1200.0))),
            "C": self._clamp_rate(290.0 + 170.0 * max(0.0, math.sin(2 * math.pi * (cycle + 200.0) / 1400.0))),
        }

    def advance_one_tick(self) -> None:
        if not self.running:
            return
        inflow_tph = self.current_inflow_rates(self.plant.time_s)
        self.last_rates_tph = inflow_tph.copy()
        if self.mode == "optimized":
            commands, diagnostics = self.optimizer.select_commands(self.plant, rate_forecaster=self.current_inflow_rates)
            self.plant.step(commands, inflow_tph, CONTROL_DT_S, apply_ramp_limit=False)
        else:
            commands, diagnostics = self.baseline.select_commands(self.plant, inflow_tph, CONTROL_DT_S)
            self.plant.step(commands, inflow_tph, CONTROL_DT_S, apply_ramp_limit=True)
        self.last_diagnostics = diagnostics
        self.record_history()

    def record_history(self) -> None:
        snapshot = {
            "time_s": self.plant.time_s,
            "total_power_kw": sum(self.plant.states[belt_id].last_power_kw for belt_id in BELT_ORDER),
            "total_energy_kwh": self.plant.total_energy_kwh(),
            "total_wear": self.plant.total_wear_index(),
            "queue_total_t": sum(self.plant.queues_t.values()),
            "main_speed_mps": self.plant.states["main"].speed_mps,
            "main_cmd_mps": float(self.last_diagnostics.get("main_target_mps", self.plant.states["main"].command_speed_mps)),
            "incline_speed_mps": self.plant.states["incline"].speed_mps,
            "incline_cmd_mps": float(self.last_diagnostics.get("incline_target_mps", self.plant.states["incline"].command_speed_mps)),
            "panel101_speed_mps": self.plant.states["panel101"].speed_mps,
            "panel101_cmd_mps": float(self.last_diagnostics.get("panel101_target_mps", self.plant.states["panel101"].command_speed_mps)),
            "main_power_kw": self.plant.states["main"].last_power_kw,
            "incline_power_kw": self.plant.states["incline"].last_power_kw,
            "panel101_power_kw": self.plant.states["panel101"].last_power_kw,
            "main_fill_ratio": self.plant.states["main"].last_fill_ratio,
            "incline_fill_ratio": self.plant.states["incline"].last_fill_ratio,
            "A_tph": self.last_rates_tph.get("A", 0.0),
            "B_tph": self.last_rates_tph.get("B", 0.0),
            "C_tph": self.last_rates_tph.get("C", 0.0),
        }
        self.history.append(snapshot)

    def _history_payload(self) -> dict[str, list[float]]:
        rows = list(self.history)
        keys = [
            "time_s",
            "total_power_kw",
            "total_energy_kwh",
            "total_wear",
            "queue_total_t",
            "main_speed_mps",
            "main_cmd_mps",
            "incline_speed_mps",
            "incline_cmd_mps",
            "panel101_speed_mps",
            "panel101_cmd_mps",
            "main_power_kw",
            "incline_power_kw",
            "panel101_power_kw",
            "main_fill_ratio",
            "incline_fill_ratio",
            "A_tph",
            "B_tph",
            "C_tph",
        ]
        return {key: [round(float(row[key]), 4) for row in rows] for key in keys}

    def _belt_payload(self, belt_id: str) -> dict[str, object]:
        cfg = self.belt_configs[belt_id]
        state = self.plant.states[belt_id]
        x_positions = np.linspace(0.0, cfg.length_m, len(state.cells_t))
        fill_ratio = state.cells_t / max(cfg.max_density_tpm * cfg.cell_length_m, 1e-6)
        queue_total = sum(
            self.plant.queues_t[point.queue_id]
            for point in self.plant.load_points_by_belt[belt_id]
            if point.queue_id in self.plant.queues_t
        )
        return {
            "id": belt_id,
            "name": cfg.name,
            "controllable": cfg.controllable,
            "speed_mps": round(state.speed_mps, 3),
            "command_speed_mps": round(state.command_speed_mps, 3),
            "power_kw": round(state.last_power_kw, 3),
            "energy_kwh": round(state.energy_kwh, 3),
            "wear_index": round(state.wear_index, 3),
            "inventory_t": round(state.inventory_t, 3),
            "outflow_tph": round(state.last_outflow_tph, 3),
            "fill_ratio": round(state.last_fill_ratio, 3),
            "queue_t": round(queue_total, 3),
            "profile": {
                "x_m": [round(float(value), 2) for value in x_positions.tolist()],
                "fill_ratio": [round(float(value), 4) for value in fill_ratio.tolist()],
            },
        }

    def payload(self) -> dict[str, object]:
        belts = [self._belt_payload(belt_id) for belt_id in BELT_ORDER]
        return {
            "running": self.running,
            "mode": self.mode,
            "scenario": self.scenario,
            "strategy": self.last_diagnostics.get("strategy", ""),
            "time_s": round(self.plant.time_s, 2),
            "summary": {
                "total_power_kw": round(sum(belt["power_kw"] for belt in belts), 3),
                "total_energy_kwh": round(self.plant.total_energy_kwh(), 3),
                "total_wear": round(self.plant.total_wear_index(), 3),
                "queue_total_t": round(sum(self.plant.queues_t.values()), 3),
                "queue_peak_t": round(self.plant.queue_peak_t, 3),
                "dispatched_t": round(self.plant.dispatched_t, 3),
            },
            "sources": {
                queue_id: {
                    "inflow_tph": round(self.last_rates_tph.get(queue_id, 0.0), 3),
                    "queue_t": round(self.plant.queues_t.get(queue_id, 0.0), 3),
                }
                for queue_id in EXTERNAL_QUEUE_IDS
            },
            "transfer_queues": {
                queue_id: round(value, 3)
                for queue_id, value in self.plant.queues_t.items()
                if queue_id not in EXTERNAL_QUEUE_IDS
            },
            "belts": belts,
            "history": self._history_payload(),
            "diagnostics": {
                key: round(float(value), 4) if isinstance(value, (float, int)) else value
                for key, value in self.last_diagnostics.items()
            },
            "settings": {
                "manual_rates_tph": self.manual_rates_tph.copy(),
                "weights": {
                    "power": self.weights.power,
                    "wear": self.weights.wear,
                    "queue": self.weights.queue,
                    "fill": self.weights.fill,
                    "ramp": self.weights.ramp,
                },
            },
        }


def build_benchmark_report(duration_s: float = 3600.0) -> dict[str, object]:
    results: dict[str, dict[str, float]] = {}
    for mode in ("baseline", "optimized"):
        engine = DashboardEngine()
        engine.mode = mode
        engine.scenario = "benchmark"
        engine.running = True
        steps = int(duration_s / CONTROL_DT_S)
        for _ in range(steps):
            engine.advance_one_tick()
        history = list(engine.history)
        avg_main_speed = float(np.mean([row["main_speed_mps"] for row in history]))
        avg_incline_speed = float(np.mean([row["incline_speed_mps"] for row in history]))
        avg_panel101_speed = float(np.mean([row["panel101_speed_mps"] for row in history]))
        peak_power = max((row["total_power_kw"] for row in history), default=0.0)
        results[mode] = {
            "energy_kwh": round(engine.plant.total_energy_kwh(), 3),
            "peak_power_kw": round(peak_power, 3),
            "wear_index": round(engine.plant.total_wear_index(), 3),
            "queue_peak_t": round(engine.plant.queue_peak_t, 3),
            "dispatched_t": round(engine.plant.dispatched_t, 3),
            "avg_main_speed_mps": round(avg_main_speed, 3),
            "avg_incline_speed_mps": round(avg_incline_speed, 3),
            "avg_panel101_speed_mps": round(avg_panel101_speed, 3),
        }

    baseline = results["baseline"]
    optimized = results["optimized"]
    delta_energy_pct = 0.0
    delta_peak_pct = 0.0
    delta_wear_pct = 0.0
    if baseline["energy_kwh"] > 0:
        delta_energy_pct = (optimized["energy_kwh"] - baseline["energy_kwh"]) / baseline["energy_kwh"] * 100.0
    if baseline["peak_power_kw"] > 0:
        delta_peak_pct = (optimized["peak_power_kw"] - baseline["peak_power_kw"]) / baseline["peak_power_kw"] * 100.0
    if baseline["wear_index"] > 0:
        delta_wear_pct = (optimized["wear_index"] - baseline["wear_index"]) / baseline["wear_index"] * 100.0

    return {
        "duration_s": duration_s,
        "scenario": "benchmark",
        "baseline": baseline,
        "optimized": optimized,
        "delta": {
            "energy_pct": round(delta_energy_pct, 3),
            "peak_power_pct": round(delta_peak_pct, 3),
            "wear_pct": round(delta_wear_pct, 3),
        },
    }


def create_app() -> Flask:
    app = Flask(__name__)
    engine = DashboardEngine()
    app.config["ENGINE"] = engine

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.get("/api/state")
    def state() -> object:
        engine = app.config["ENGINE"]
        engine.advance_one_tick()
        return jsonify(engine.payload())

    @app.post("/api/control")
    def control() -> object:
        engine = app.config["ENGINE"]
        payload = request.get_json(silent=True) or {}
        engine.update_settings(payload)
        return jsonify(engine.payload())

    @app.post("/api/reset")
    def reset() -> object:
        engine = app.config["ENGINE"]
        payload = request.get_json(silent=True) or {}
        engine.update_settings(payload)
        engine.reset()
        return jsonify(engine.payload())

    @app.get("/api/benchmark")
    def benchmark() -> object:
        duration_s = float(request.args.get("duration_s", 3600.0))
        return jsonify(build_benchmark_report(duration_s))

    return app


def run_smoke_test() -> None:
    app = create_app()
    client = app.test_client()
    first_payload = client.get("/api/state").get_json()
    assert first_payload["summary"]["total_power_kw"] >= 0.0
    assert len(first_payload["belts"]) == 3

    control_payload = client.post(
        "/api/control",
        json={
            "mode": "baseline",
            "scenario": "wave",
            "running": False,
            "manual_rates_tph": {"A": 460.0, "B": 320.0, "C": 280.0},
        },
    ).get_json()
    assert control_payload["mode"] == "baseline"
    assert control_payload["running"] is False

    reset_payload = client.post(
        "/api/reset",
        json={
            "mode": "optimized",
            "scenario": "manual",
            "running": True,
            "manual_rates_tph": {"A": 400.0, "B": 240.0, "C": 260.0},
        },
    ).get_json()
    assert reset_payload["scenario"] == "manual"
    benchmark_payload = client.get("/api/benchmark?duration_s=1200").get_json()
    assert "baseline" in benchmark_payload and "optimized" in benchmark_payload
    print("SMOKE_TEST_OK")
    print(benchmark_payload)


def print_benchmark_report(duration_s: float) -> None:
    report = build_benchmark_report(duration_s)
    print("=== 对比场景结果（示例场景，不代表现场标定值） ===")
    print(f"仿真时长: {duration_s:.0f} s")
    for mode in ("baseline", "optimized"):
        row = report[mode]
        print(
            f"[{mode}] 电耗={row['energy_kwh']:.3f} kWh, 峰值功率={row['peak_power_kw']:.3f} kW, "
            f"磨损指数={row['wear_index']:.3f}, 队列峰值={row['queue_peak_t']:.3f} t, "
            f"平均主运速度={row['avg_main_speed_mps']:.3f} m/s, 平均斜井速度={row['avg_incline_speed_mps']:.3f} m/s, "
            f"平均101速度={row['avg_panel101_speed_mps']:.3f} m/s"
        )
    delta = report["delta"]
    print(
        f"优化相对基线: 电耗 {delta['energy_pct']:.3f}% , 峰值功率 {delta['peak_power_pct']:.3f}% , "
        f"磨损 {delta['wear_pct']:.3f}%"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="煤流协同优化控制 Web 仿真")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--benchmark", action="store_true", help="运行基线和优化策略对比")
    parser.add_argument("--benchmark-duration", type=float, default=3600.0, help="对比仿真时长（秒）")
    parser.add_argument("--smoke-test", action="store_true", help="运行接口与算法冒烟测试")
    args = parser.parse_args()

    if args.smoke_test:
        run_smoke_test()
        return
    if args.benchmark:
        print_benchmark_report(args.benchmark_duration)
        return

    app = create_app()
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()

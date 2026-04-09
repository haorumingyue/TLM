"""仿真与前端之间的线程安全快照：节能率、历史曲线、预测与调速事件等。"""
import os
import threading

from .config import WebConfig


class SimState:
    """持有暂停/自动调速等 UI 状态，并将多皮带仿真结果序列化为 API 负载。"""

    def __init__(self):
        self._lk = threading.RLock()
        self.paused = False
        self.auto_speed = True
        self.model_ready = False
        self.data = {}
        self._last_pred = [None, None]
        self._last_csv_write = 0.0

    def snapshot(self, sim, sim_const, replay, pred):
        ds = WebConfig.BELT_DOWNSAMPLE
        cfg = WebConfig
        # 基于真实物理积累的做功量计算百分比节能（对比额定常速对照组）
        if sim_const.energy_acc > 1e-6:
            saving = max(0.0, (sim_const.energy_acc - sim.energy_acc) / sim_const.energy_acc * 100)
        else:
            saving = 0.0
        saving_kwh = max(0.0, sim_const.energy_acc - sim.energy_acc)
        N = cfg.N_HISTORY
        lanes_out = []
        for i, queue_id in enumerate(cfg.INFLOW_QUEUES):
            c = replay.cache[i]
            if c is not None:
                self._last_pred[i] = c
            use = self._last_pred[i]
            # 主运皮带上对应入流点的流量历史
            hist_t_raw = sim.t_hist[-N:]
            hist_flow_raw = sim.flow_hist.get(queue_id, [])[-N:] if sim.flow_hist.get(queue_id) else [0.0] * len(hist_t_raw)
            hist_pred = []
            for tt in hist_t_raw:
                log_idx = int(tt / WebConfig.LOG_INTERVAL_SEC)
                pv = replay.pred_buf[i].get(log_idx)
                hist_pred.append(round(pv, 4) if pv is not None else None)
            lanes_out.append(
                {
                    "name": cfg.FACE_NAMES[i],
                    "hist_t": [round(v, 1) for v in hist_t_raw],
                    "hist_flow": [round(v, 4) for v in hist_flow_raw],
                    "hist_pred": hist_pred,
                    "pred_t": [round(v, 1) for v in (use[0].tolist() if use else [])],
                    "pred_low": [round(v, 4) for v in (use[1].tolist() if use else [])],
                    "pred_med": [round(v, 4) for v in (use[2].tolist() if use else [])],
                    "pred_high": [round(v, 4) for v in (use[3].tolist() if use else [])],
                    "now_actual": round(sim.rates.get(queue_id, 0.0), 4),
                    "now_pred": round(float(use[2][0]), 4) if use else None,
                }
            )

        # 调速事件（主运皮带）
        speed_events = [
            {
                "t_start": round(e["t_start"], 1),
                "t_end": (round(e["t_end"], 1) if e["t_end"] is not None else None),
                "speed": round(e["speed"], 4),
                "duration": (
                    round((e["t_end"] - e["t_start"]), 1)
                    if e["t_end"] is not None
                    else None
                ),
            }
            for e in sim.belts["main"].speed_events
        ]

        # CSV 节流
        sim_t = sim.time
        if sim_t - self._last_csv_write >= 10.0:
            self._last_csv_write = sim_t
            try:
                import csv
                os.makedirs("logs", exist_ok=True)
                with open("logs/speed_events.csv", "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["t_start_s", "t_end_s", "duration_s", "speed_m_per_s"])
                    for ev in speed_events:
                        writer.writerow([
                            ev["t_start"],
                            ev["t_end"] if ev["t_end"] is not None else "",
                            ev["duration"] if ev["duration"] is not None else "",
                            ev["speed"],
                        ])
            except Exception:
                pass

        # 三条皮带各自的快照数据
        def belt_snapshot(belt_id, sim_obj):
            b = sim_obj.belts[belt_id]
            bcfg = cfg.BELT_CONFIGS[belt_id]
            ds_b = max(1, int(bcfg["cell_length"] / cfg.BELT_MAIN["cell_length"])) if belt_id != "main" else ds
            return {
                "name": bcfg["name"],
                "speed": round(b.speed, 4),
                "power_kw": round(b.last_power_kw, 2),
                "inventory_t": round(b.inventory_t, 2),
                "fill_ratio": round(b.last_fill_ratio, 4),
                "wear_index": round(b.wear_index, 4),
                "energy_kwh": round(b.energy_kwh, 4),
                "outflow_tph": round(b.last_outflow_tph, 2),
                "pos": [round(v, 0) for v in b.get_pos()[::ds_b].tolist()],
                "load": [round(float(v), 4) for v in b.cells[::ds_b].tolist()],
            }

        total_power_ai = sum(sim.belts[bid].last_power_kw for bid in cfg.BELT_ORDER)
        total_power_const = sum(sim_const.belts[bid].last_power_kw for bid in cfg.BELT_ORDER)

        with self._lk:
            self.model_ready = pred.ready
            self.data = {
                "paused": self.paused,
                "auto_speed": self.auto_speed,
                "model_ready": pred.ready,
                "sim_time": round(sim.time, 1),
                "saving_pct": round(saving, 2),
                "saving_kwh": round(saving_kwh, 4),
                "total_power_kw": round(total_power_ai, 2),
                "total_power_const_kw": round(total_power_const, 2),
                "total_energy_kwh": round(sim.energy_acc, 4),
                "total_energy_baseline_kwh": round(sim_const.energy_acc, 4),
                "total_wear": round(sum(b.wear_index for b in sim.belts.values()), 4),
                "dispatched_t": round(sim.dispatched, 2),
                "queues": {q: round(v, 2) for q, v in sim.queues.items()},
                "scenario_const": {
                    "speed": round(sim_const.belts["main"].speed, 4),
                    "power_kw": round(total_power_const, 2),
                    "on_belt": round(sim_const.stats["coal"], 4),
                    "total_out": round(sim_const.total_out, 4),
                },
                "scenario_ai": {
                    "speed": round(sim.belts["main"].speed, 4),
                    "power_kw": round(total_power_ai, 2),
                    "on_belt": round(sim.stats["coal"], 4),
                    "total_out": round(sim.total_out, 4),
                },
                "belts": {bid: belt_snapshot(bid, sim) for bid in cfg.BELT_ORDER},
                "belts_const": {bid: belt_snapshot(bid, sim_const) for bid in cfg.BELT_ORDER},
                "lanes": lanes_out,
                "spd_t": [round(v, 1) for v in sim.t_hist[-N:]],
                "spd_v": [round(v, 4) for v in sim.spd_hist[-N:]],
                "cumin": [round(v, 4) for v in sim.cumin_hist[-N:]],
                "cumout": [round(v, 4) for v in sim.cumout_hist[-N:]],
                "coal": [round(v, 4) for v in sim.coal_hist[-N:]],
                "energy_ai": [round(v, 4) for v in sim.energy_hist[-N:]],
                "energy_const": [round(v, 4) for v in sim_const.energy_hist[-N:]],
                "power_kw_hist": [round(v, 2) for v in sim.power_hist[-N:]],
                "pred_queue": list(replay.q_size),
                "speed_events": speed_events,
                "lane_flow_ymax": round(
                    (cfg.MAX_RAW_TRAFFIC / cfg.LOG_INTERVAL_SEC) * cfg.LANE_FLOW_Y_HEADROOM, 4
                ),
            }

    def get(self):
        with self._lk:
            return dict(self.data)

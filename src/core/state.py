import threading

from .config import WebConfig


class SimState:
    def __init__(self):
        self._lk = threading.RLock()
        self.paused = False
        self.auto_speed = True
        self.model_ready = False
        self.data = {}
        self._last_pred = [None, None]

    def snapshot(self, sim, sim_const, replay, pred):
        ds = WebConfig.BELT_DOWNSAMPLE
        cfg = WebConfig
        # 基于真实物理积累的做功量计算百分比节能（对比额定常速对照组）
        if sim_const.energy_acc > 1e-6:
            saving = max(0.0, (sim_const.energy_acc - sim.energy_acc) / sim_const.energy_acc * 100)
        else:
            saving = 0.0
        N = cfg.N_HISTORY
        lanes_out = []
        for i, pos in enumerate(cfg.INFLOW_POSITIONS):
            c = replay.cache[i]
            if c is not None:
                self._last_pred[i] = c
            use = self._last_pred[i]
            hist_t_raw = sim.t_hist[-N:]
            hist_flow_raw = sim.flow_hist[pos][-N:]
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
                    "now_actual": round(sim.rates[i], 4),
                    "now_pred": round(float(use[2][0]), 4) if use else None,
                }
            )
        # 基于当前仿真时间轴整理调速事件（所有时间均为“仿真时间”）
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
            for e in getattr(sim, "speed_events", [])
        ]

        # 将调速事件快照输出到本地 CSV 文档，便于离线分析
        # 文件包含：仿真起止时间、持续时长（秒）、对应带速
        try:
            import csv

            with open("logs/speed_events.csv", "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["t_start_s", "t_end_s", "duration_s", "speed_m_per_s"])
                for ev in speed_events:
                    writer.writerow(
                        [
                            ev["t_start"],
                            ev["t_end"] if ev["t_end"] is not None else "",
                            ev["duration"] if ev["duration"] is not None else "",
                            ev["speed"],
                        ]
                    )
        except Exception:
            # 本地写文件失败时不影响前端显示
            pass

        with self._lk:
            self.model_ready = pred.ready
            self.data = {
                "paused": self.paused,
                "auto_speed": self.auto_speed,
                "model_ready": pred.ready,
                "sim_time": round(sim.time, 1),
                "belt_pos": [round(v, 0) for v in sim.get_pos()[::ds].tolist()],
                "belt_load": [round(v, 4) for v in sim.bl[::ds].tolist()],
                "belt_const_load": [round(v, 4) for v in sim_const.bl[::ds].tolist()],
                "avg_power": round(sim.energy_acc / max(sim.time_acc, 1e-6), 4),
                "rec_speed": round(sim.speed, 4),
                "actual_speed": cfg.ACTUAL_SPEED,
                "saving_pct": round(saving, 2),
                "scenario_const": {
                    "speed": round(sim_const.speed, 4),
                    "on_belt": round(sim_const.stats["coal"], 4),
                    "total_in": round(sum(sim_const.total_in.values()), 4),
                    "total_out": round(sim_const.total_out, 4),
                },
                "scenario_ai": {
                    "speed": round(sim.speed, 4),
                    "on_belt": round(sim.stats["coal"], 4),
                    "total_in": round(sum(sim.total_in.values()), 4),
                    "total_out": round(sim.total_out, 4),
                },
                "lanes": lanes_out,
                "spd_t": [round(v, 1) for v in sim.t_hist[-N:]],
                "spd_v": [round(v, 4) for v in sim.spd_hist[-N:]],
                "cumin": [round(v, 4) for v in sim.cumin_hist[-N:]],
                "cumout": [round(v, 4) for v in sim.cumout_hist[-N:]],
                "coal": [round(v, 4) for v in sim.coal_hist[-N:]],
                "pred_queue": list(replay.q_size),
                "speed_events": speed_events,
                "lane_flow_ymax": round(
                    (cfg.MAX_RAW_TRAFFIC / cfg.LOG_INTERVAL_SEC) * cfg.LANE_FLOW_Y_HEADROOM, 4
                ),
            }

    def get(self):
        with self._lk:
            return dict(self.data)

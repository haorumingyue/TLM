import numpy as np

from .config import WebConfig


class PIDStrategy:
    V_MIN, V_MAX, L_OPT = 1.5, 4.5, 0.15

    def __init__(self):
        self._integ = 0.0
        self._fv = self.V_MAX
        self._last_v = self.V_MAX
        self._ilim = 0.5

    def calc(self, spd, inflow, max_load, dt, belt_load=None, pred_inflow=None):
        if belt_load is not None and len(belt_load):
            w = np.linspace(1.0, 0.2, len(belt_load))
            s_max = float(np.max(belt_load * w))
        else:
            s_max = max_load

        if s_max > self.L_OPT * 1.5:
            ns = min(self.V_MAX, self._last_v + 0.15 * dt)
            self._fv = ns
            self._last_v = ns
            self._integ = 0.0
            return ns

        ref = max(inflow, float(np.max(pred_inflow))) if pred_inflow is not None and len(pred_inflow) else inflow
        
        # 核心修复 1：纯前馈计算，打破因为传入实际 discrete spd 导致的 "密度跳变错觉"
        # 目标带速仅受 "需要消化多少流量保证 0.9*L_OPT" 决定
        v_flow = (ref * WebConfig.CELL_SIZE) / (self.L_OPT * 0.90)
        
        # 核心修复 2：真实载荷兜底。仅当实质皮带局部异常拥堵时才强制施加底线速度
        v_feedback = 0.0
        if s_max > self.L_OPT:
            excess_ratio = (s_max - self.L_OPT) / (0.5 * self.L_OPT)
            v_feedback = self.V_MIN + excess_ratio * (self.V_MAX - self.V_MIN)
            
        ideal = max(self.V_MIN, min(self.V_MAX, max(v_flow, v_feedback)))

        # 核心修复 3：相对于自身连续目标状态 `_last_v` 进行积分，而非离散实际带速 `spd`
        # （如果按 spd 积分会吃满由档位量子化带来的稳态误差，产生强制上下跳档的极限环震荡）
        dr = abs(ideal - self._last_v) / max(self._last_v, 1e-6)
        if dr < 0.02:
            self._integ *= 0.98
        else:
            self._integ = np.clip(self._integ + 0.05 * (ideal - self._last_v) * dt, -self._ilim, self._ilim)
        
        tgt = max(self.V_MIN, min(self.V_MAX, ideal + self._integ))

        alpha = dt / (2.0 + dt)
        self._fv = self._fv * (1 - alpha) + tgt * alpha
        dv = 0.15 * dt
        if self._fv > self._last_v + 0.005:
            self._last_v = min(self._fv, self._last_v + dv)
        elif self._fv < self._last_v - 0.005:
            self._last_v = max(self._fv, self._last_v - dv)
        else:
            self._last_v = self._fv
        return self._last_v

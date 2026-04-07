"""离散仿真用 PID 策略：连续理想带速 + 积分，供外层档位量化使用。"""
import numpy as np

from .config import WebConfig


class PIDStrategy:
    """根据入流、预测与皮带载荷计算连续目标带速（非直接输出离散档位）。"""

    V_MIN, V_MAX, L_OPT = 1.5, 4.5, 0.15

    def __init__(self):
        self._integ = 0.0
        self._fv = self.V_MAX
        self._last_v = self.V_MAX
        self._ilim = 0.5

    def calc(self, spd, inflow, max_load, dt, belt_load=None, pred_inflow=None):
        """
        计算下一时刻的连续理想带速。

        spd: 当前实际带速（档位量化值，积分路径中刻意弱化其影响以避免极限环）。
        inflow: 当前总入流（t/s）；pred_inflow: 预测步上的入流序列（可选）。
        belt_load: 各格煤量，用于加权估计局部拥堵；max_load: 全局最大线密度上界。
        """
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
        
        # 前馈：按 ref 与目标线密度推算所需带速，不依赖当前离散 spd，避免“密度跳变”误判
        v_flow = (ref * WebConfig.CELL_SIZE) / (self.L_OPT * 0.90)
        
        # 反馈兜底：线密度超过 L_OPT 时按拥堵程度抬高目标带速下限
        v_feedback = 0.0
        if s_max > self.L_OPT:
            excess_ratio = (s_max - self.L_OPT) / (0.5 * self.L_OPT)
            v_feedback = self.V_MIN + excess_ratio * (self.V_MAX - self.V_MIN)
            
        ideal = max(self.V_MIN, min(self.V_MAX, max(v_flow, v_feedback)))

        # 积分对象用连续状态 _last_v，不用离散 spd，避免档位量化误差在积分中累积引发换挡震荡
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

"""离散仿真用 PID 策略：连续理想带速 + 积分，供外层档位量化使用。

优化项：
- belt_load 权重指向装料端（尾部拥堵风险最高）
- v_feedback 和 v_penalty 合并为单一超填响应
- 前馈使用预测轨迹加权衰减，而非单一最大值
- 积分衰减按 dt 归一化
"""
import numpy as np


class PIDStrategy:
    """根据入流、预测与皮带载荷计算连续目标带速（非直接输出离散档位）。"""

    V_MIN, V_MAX = 1.5, 4.5  # 与皮带 min/max_speed 对齐
    # L_OPT: 目标填料比（0~1），皮带在此填料比下为最优节能运行点
    # 0.6 表示皮带 60% 满载时速度恰好匹配入流，超过则加速，低于则减速
    L_OPT = 0.60

    def __init__(self):
        self._integ = 0.0
        self._fv = self.V_MAX
        self._last_v = self.V_MAX
        self._ilim = 0.5

    def calc(self, spd, inflow, max_load, dt, belt_load=None, pred_inflow=None, max_density=None):
        """
        计算下一时刻的连续理想带速。

        spd: 当前实际带速（档位量化值）。
        inflow: 当前总入流（t/s）。
        max_load: 全局最大填料比（0~1）。
        dt: 仿真步长（s）。
        belt_load: 各格填料比（0~1），用于加权估计局部拥堵。
        pred_inflow: 预测步上的入流序列（可选）。
        max_density: 皮带最大线密度（t/m），用于前馈带速推算。
        """
        # ── 1. 局部拥堵检测：装料端（尾部）权重最高 ──
        if belt_load is not None and len(belt_load):
            w = np.linspace(0.2, 1.0, len(belt_load))
            s_max = float(np.max(belt_load * w))
        else:
            s_max = max_load

        # ── 2. 前馈：按入流推算维持目标填料比所需带速 ──
        if pred_inflow is not None and len(pred_inflow):
            n = len(pred_inflow)
            decay = np.array([1.0 / (1.0 + 0.3 * k) for k in range(n)])
            ref_pred = float(np.max(pred_inflow * decay))
            ref = max(inflow, ref_pred)
        else:
            ref = inflow

        # v = ref / (max_density * L_OPT)：使填料比达到 L_OPT 所需的带速
        if max_density and max_density > 0:
            v_flow = ref / (max_density * self.L_OPT)
        else:
            v_flow = ref / (self.L_OPT * 0.90)

        # ── 3. 超填响应：当填料比超过 L_OPT 时平滑推高带速 ──
        if s_max > self.L_OPT and v_flow < self.V_MAX:
            excess = (s_max - self.L_OPT) / self.L_OPT
            t = min(1.0, excess)
            v_overfill = v_flow + t * (self.V_MAX - v_flow)
        else:
            v_overfill = v_flow

        ideal = max(self.V_MIN, min(self.V_MAX, v_overfill))

        # ── 4. 积分：衰减按 dt 归一化 ──
        dr = abs(ideal - self._last_v) / max(self._last_v, 1e-6)
        if dr < 0.02:
            # 目标已到达，按 2%/s 衰减（dt 归一化）
            self._integ *= (1.0 - 0.02 * dt)
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

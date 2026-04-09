"""PID 策略单元测试。"""
import numpy as np
import pytest

from src.core.pid import PIDStrategy


class TestPIDStrategy:
    def test_zero_inflow_returns_valid_speed(self):
        pid = PIDStrategy()
        v = pid.calc(3.0, 0.0, 0.0, 0.1)
        assert pid.V_MIN <= v <= pid.V_MAX

    def test_high_inflow_increases_speed(self):
        pid = PIDStrategy()
        v_start = pid.calc(1.5, 0.1, 0.05, 0.1)
        for _ in range(50):
            v_start = pid.calc(v_start, 1.0, 0.2, 0.1)
        v_high = pid.calc(v_start, 1.0, 0.2, 0.1)
        assert v_high > pid.V_MIN + 0.1

    def test_overfill_smooth_penalty(self):
        """超填惩罚是平滑二次项，非硬阈值突跳。"""
        # 正常负载
        pid1 = PIDStrategy()
        v_normal = pid1.calc(2.0, 0.3, 0.1, 0.1)
        # 超填负载（加权后 s_max > L_OPT）
        pid2 = PIDStrategy()
        big_load = np.array([0.25] * 100)
        v_overfill = pid2.calc(2.0, 0.3, 0.1, 0.1, belt_load=big_load)
        # 超填时目标速度应不低于正常（惩罚驱动速度升高以疏散）
        assert v_overfill >= v_normal - 0.01

    def test_pred_inflow_used_as_ref(self):
        pid1 = PIDStrategy()
        pid2 = PIDStrategy()
        dt = 0.1
        v1 = pid1.calc(2.0, 0.5, 0.1, dt)
        pred = np.array([1.2, 1.3, 1.1])
        v2 = pid2.calc(2.0, 0.5, 0.1, dt, pred_inflow=pred)
        assert v2 >= v1

    def test_speed_clamped_to_range(self):
        pid = PIDStrategy()
        v = pid.calc(pid.V_MAX, 0.0, 0.0, 0.1)
        assert v <= pid.V_MAX
        v = pid.calc(pid.V_MIN, 0.0, 0.0, 0.1)
        assert v >= pid.V_MIN

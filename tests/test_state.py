"""SimState 快照与线程安全单元测试。"""
import threading
import time

import pytest

from src.core.config import WebConfig
from src.core.simulator import Simulator
from src.core.state import SimState


def _make_state():
    """创建一个带基本仿真数据的 SimState。"""
    sim = Simulator(fixed_speed=True)
    sim_const = Simulator(fixed_speed=True)
    sim.set_rate(0, 0.5)
    for _ in range(50):
        sim.step()
        sim_const.step()
    state = SimState()
    return state, sim, sim_const


class MockPred:
    ready = False


class MockReplay:
    cache = [None, None]
    pred_buf = [{}, {}]
    q_size = [0, 0]


class TestSimState:
    def test_get_returns_dict(self):
        state = SimState()
        d = state.get()
        assert isinstance(d, dict)

    def test_get_returns_copy(self):
        state = SimState()
        d1 = state.get()
        d2 = state.get()
        assert d1 is not d2  # 应该是副本

    def test_set_control_paused(self):
        state = SimState()
        state.set_control(paused=True)
        paused, auto_speed = state.get_control()
        assert paused is True
        assert auto_speed is True  # 未改变

    def test_set_control_auto_speed(self):
        state = SimState()
        state.set_control(auto_speed=False)
        paused, auto_speed = state.get_control()
        assert paused is False  # 未改变
        assert auto_speed is False

    def test_set_control_both(self):
        state = SimState()
        state.set_control(paused=True, auto_speed=False)
        paused, auto_speed = state.get_control()
        assert paused is True
        assert auto_speed is False

    def test_snapshot_produces_expected_keys(self):
        state, sim, sim_const = _make_state()
        replay = MockReplay()
        pred = MockPred()
        state.snapshot(sim, sim_const, replay, pred)
        d = state.get()
        expected_keys = [
            "paused", "auto_speed", "model_ready", "sim_time",
            "saving_pct", "saving_kwh", "total_power_kw", "total_power_const_kw",
            "total_energy_kwh", "total_energy_baseline_kwh", "total_wear",
            "dispatched_t", "queues", "scenario_const", "scenario_ai",
            "belts", "belts_const", "lanes",
            "spd_t", "spd_v", "cumin", "cumout", "coal",
            "energy_ai", "energy_const", "power_kw_hist",
            "pred_queue", "speed_events", "lane_flow_ymax",
        ]
        for key in expected_keys:
            assert key in d, f"缺少 key: {key}"

    def test_belt_snapshot_structure(self):
        state, sim, sim_const = _make_state()
        replay = MockReplay()
        pred = MockPred()
        state.snapshot(sim, sim_const, replay, pred)
        d = state.get()
        for bid in WebConfig.BELT_ORDER:
            belt = d["belts"][bid]
            for key in ("name", "speed", "power_kw", "inventory_t", "fill_ratio",
                        "wear_index", "energy_kwh", "outflow_tph", "pos", "load"):
                assert key in belt, f"皮带 {bid} 缺少 key: {key}"

    def test_thread_safe_concurrent_access(self):
        """并发读写 SimState 不应崩溃。"""
        state = SimState()
        errors = []

        def writer():
            try:
                for _ in range(100):
                    state.set_control(paused=True, auto_speed=False)
                    state.set_control(paused=False, auto_speed=True)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(100):
                    state.get_control()
                    state.get()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer), threading.Thread(target=reader),
                   threading.Thread(target=writer), threading.Thread(target=reader)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)
        assert not errors, f"并发访问出错: {errors}"

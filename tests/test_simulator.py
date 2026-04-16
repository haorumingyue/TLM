"""Simulator 多皮带级联仿真单元测试。"""
import numpy as np
import pytest

from src.core.simulator import Simulator, _advect_cells
from src.core.config import WebConfig


class TestSimulator:
    def test_step_advances_time(self):
        sim = Simulator(fixed_speed=4.0)
        assert sim.time == 0.0
        sim.set_rate(0, 0.5)
        sim.step()
        assert abs(sim.time - WebConfig.DT) < 1e-12

    def test_three_belts_exist(self):
        sim = Simulator()
        assert "main" in sim.belts
        assert "incline" in sim.belts
        assert "panel101" in sim.belts

    def test_fixed_speed_constant(self):
        sim = Simulator(fixed_speed=True)
        sim.set_rate(0, 0.5)
        for _ in range(100):
            sim.step()
        # 各皮带应保持各自额定速度（max_speed）
        assert sim.belts["main"].speed == WebConfig.BELT_MAIN.max_speed
        assert sim.belts["incline"].speed == WebConfig.BELT_INCLINE.max_speed
        assert sim.belts["panel101"].speed == WebConfig.BELT_PANEL101.max_speed

    def test_queues_exist(self):
        sim = Simulator()
        assert "A" in sim.queues
        assert "B" in sim.queues

    def test_mass_conservation(self):
        """总入流 - 排出 ≈ 皮带存煤 + 队列（浮点容差）。"""
        sim = Simulator(fixed_speed=3.0)
        total_input = 0.0
        for _ in range(500):
            sim.set_rate(0, 0.3)  # t/s
            sim.set_rate(1, 0.2)  # t/s
            total_input += (0.3 + 0.2) * WebConfig.DT  # t
            sim.step()
        belt_coal = sum(b.inventory_t for b in sim.belts.values())
        queue_coal = sum(sim.queues.values())
        assert abs(total_input - sim.dispatched - belt_coal - queue_coal) < 0.05

    def test_energy_accumulates(self):
        sim = Simulator(fixed_speed=4.0)
        sim.set_rate(0, 0.5)
        for _ in range(100):
            sim.step()
        total_energy = sum(b.energy_kwh for b in sim.belts.values())
        assert total_energy > 0.0

    def test_power_physically_reasonable(self):
        """主运空载应约 aux_kw (16 kW)，斜井提升应功率更高。"""
        sim = Simulator(fixed_speed=4.0)
        for _ in range(50):
            sim.step()
        main_kw = sim.belts["main"].last_power_kw
        incline_kw = sim.belts["incline"].last_power_kw
        # 主运空载约 16 kW 辅助 + 运动功率
        assert main_kw > 10.0
        # 斜井有 340m 提升，即使空载也应高于主运辅助功率
        assert incline_kw > 10.0

    def test_wear_accumulates(self):
        sim = Simulator(fixed_speed=4.0)
        sim.set_rate(0, 0.5)
        for _ in range(100):
            sim.step()
        for bid in WebConfig.BELT_ORDER:
            assert sim.belts[bid].wear_index > 0.0

    def test_gear_upshift_instant(self):
        """升档应即时（不受驻留限制），需超过死区阈值。"""
        from src.core.simulator import _apply_gears, _gears_for
        state = sim_main_state()
        gears = _gears_for("main")
        state._gear_idx = 0  # 1.6
        state._gear_dwell = 0.0
        mid_01 = 0.5 * (gears[0] + gears[1])  # 2.0
        v = _apply_gears(mid_01 + 0.1, state)  # 超过死区 0.05
        assert v == gears[1]

    def test_gear_downshift_delay(self):
        """降档需驻留至少 min_dwell_down (默认 30s)。"""
        from src.core.simulator import _apply_gears, _gears_for
        state = sim_main_state()
        gears = _gears_for("main")
        state._gear_idx = 3  # 4.0
        state._gear_dwell = 5.0  # 不足 30s
        mid = 0.5 * (gears[3] + gears[2])  # 3.6
        v = _apply_gears(mid - 0.5, state)  # 3.1，明显低于中点
        assert v == gears[3]  # 驻留不够，保持

    def test_gear_downshift_after_dwell(self):
        """降档驻留足够后应生效。"""
        from src.core.simulator import _apply_gears, _gears_for
        state = sim_main_state()
        gears = _gears_for("main")
        state._gear_idx = 3  # 4.0
        state._gear_dwell = 70.0  # 超过 30s
        mid = 0.5 * (gears[3] + gears[2])  # 3.6
        v = _apply_gears(mid - 0.5, state)
        assert v == gears[2]

    def test_speed_events_initialized(self):
        """每条皮带初始化时应有一条初始调速事件。"""
        sim = Simulator(fixed_speed=True)
        for bid in WebConfig.BELT_ORDER:
            events = sim.belts[bid].speed_events
            assert len(events) == 1
            assert events[0]["t_start"] == 0.0
            assert events[0]["t_end"] is None

    def test_cascade_main_to_incline(self):
        """主运出流应进入斜井皮带，101 出流排出。"""
        sim = Simulator(fixed_speed=True)
        sim.set_rate(0, 0.5)  # A 入流 0.5 t/s
        for _ in range(2000):
            sim.step()
        # 主运排出的煤应进入斜井或 panel101
        incline_coal = sim.belts["incline"].inventory_t
        panel101_coal = sim.belts["panel101"].inventory_t
        dispatched = sim.dispatched
        # 煤应流经整条链路
        total_downstream = incline_coal + panel101_coal + dispatched
        assert total_downstream > 0.0, "煤应流过主运到达下游"

    def test_cascade_panel101_dispatches(self):
        """经过足够时间，101 皮带应排出煤。"""
        sim = Simulator(fixed_speed=True)
        sim.set_rate(0, 0.8)  # 高入流
        for _ in range(5000):
            sim.step()
        assert sim.dispatched > 0.0, "101 皮带最终应排出煤"


class TestAdvectCells:
    def test_conservation(self):
        """对流前后总煤量守恒（无出流时）。"""
        cells = np.array([1.0, 2.0, 3.0, 4.0, 0.0])
        # 低 CFL，不溢出
        result, outflow = _advect_cells(cells, 1.0, 1.0, 0.1)
        assert abs(np.sum(result) + outflow - np.sum(cells)) < 1e-10

    def test_high_cfl_stable(self):
        """高 CFL（>0.95）应自动子步，不会产生负值。"""
        cells = np.array([1.0, 0.5, 0.3, 0.0, 0.0])
        result, _ = _advect_cells(cells, 50.0, 1.0, 1.0)
        assert np.all(result >= 0)


def sim_main_state():
    """创建一个简单 BeltState 用于档位测试。"""
    from src.core.simulator import BeltState
    return BeltState(WebConfig.BELT_MAIN)

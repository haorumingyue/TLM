"""WebConfig 配置校验单元测试。"""
import pytest

from src.core.config import WebConfig


class TestWebConfig:
    def test_validate_passes(self):
        """当前默认配置应通过校验。"""
        WebConfig.validate()  # 不应抛出异常

    def test_belt_order_consistent(self):
        """BELT_ORDER 中的每个 ID 都应在 BELT_CONFIGS 中。"""
        for bid in WebConfig.BELT_ORDER:
            assert bid in WebConfig.BELT_CONFIGS

    def test_belt_speed_ranges(self):
        """每条皮带 min_speed < max_speed。"""
        for bid in WebConfig.BELT_ORDER:
            cfg = WebConfig.BELT_CONFIGS[bid]
            assert cfg.min_speed < cfg.max_speed

    def test_belt_lengths_positive(self):
        """每条皮带长度 > 0。"""
        for bid in WebConfig.BELT_ORDER:
            cfg = WebConfig.BELT_CONFIGS[bid]
            assert cfg.length > 0
            assert cfg.cell_length > 0

    def test_belt_efficiency_range(self):
        """效率应在 (0, 1] 范围内。"""
        for bid in WebConfig.BELT_ORDER:
            cfg = WebConfig.BELT_CONFIGS[bid]
            assert 0 < cfg.efficiency <= 1.0

    def test_speed_gears_sorted(self):
        """速度档位应严格递增。"""
        gears = WebConfig.SPEED_GEARS
        for i in range(len(gears) - 1):
            assert gears[i] < gears[i + 1]

    def test_speed_gears_match_belt_range(self):
        """速度档位应在皮带 min/max 范围内。"""
        gears = WebConfig.SPEED_GEARS
        assert gears[0] >= WebConfig.BELT_MAIN.min_speed
        assert gears[-1] <= WebConfig.BELT_MAIN.max_speed

    def test_validate_rejects_bad_min_speed(self):
        """min_speed >= max_speed 应触发校验失败。"""
        orig = WebConfig.BELT_MAIN.min_speed
        WebConfig.BELT_MAIN.min_speed = 5.0  # 大于 max_speed=4.5
        try:
            with pytest.raises(ValueError, match="min_speed"):
                WebConfig.validate()
        finally:
            WebConfig.BELT_MAIN.min_speed = orig

    def test_validate_rejects_bad_efficiency(self):
        """efficiency 超出范围应触发校验失败。"""
        orig = WebConfig.BELT_MAIN.efficiency
        WebConfig.BELT_MAIN.efficiency = 1.5
        try:
            with pytest.raises(ValueError, match="efficiency"):
                WebConfig.validate()
        finally:
            WebConfig.BELT_MAIN.efficiency = orig

    def test_inflow_queues_match_load_points(self):
        """INFLOW_QUEUES 应覆盖所有 LOAD_POINTS 的 queue ID。"""
        lp_queues = {lp.queue for lp in WebConfig.LOAD_POINTS}
        for q in lp_queues:
            assert q in WebConfig.INFLOW_QUEUES

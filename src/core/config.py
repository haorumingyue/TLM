"""Web 仿真与仪表盘专用配置（与历史桌面版配置分离，便于单独调参）。
物理参数来源：0756/app.py BeltConfig，三条皮带级联布局。
"""
import os
from dataclasses import dataclass, field
from typing import List

# 项目根目录（config.py → core → src → TLM）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class BeltConfig:
    """单条皮带的物理与磨损参数（类型安全、IDE 可补全）。"""

    id: str
    name: str
    length: float           # 皮带长度 (m)
    cell_length: float      # 仿真格元长度 (m)
    min_speed: float        # 最低带速 (m/s)
    max_speed: float        # 最高带速 (m/s)
    max_density: float      # 最大线密度 (t/m)
    empty_mass_kg_m: float  # 空载线质量 (kg/m)
    resistance: float       # 阻力系数
    efficiency: float       # 驱动效率 (0, 1]
    lift_m: float           # 提升高度 (m)
    aux_kw: float           # 辅助功率 (kW)
    wear_speed: float       # 速度磨损系数
    wear_load: float        # 负载磨损系数
    wear_ramp: float        # 加速度磨损系数


@dataclass
class LoadPointConfig:
    """转载点/入料点配置。"""

    id: str
    name: str
    belt: str       # 所属皮带 ID
    pos: float      # 在皮带上的位置 (m)
    queue: str      # 对应的入流队列 ID
    max_tph: float  # 最大装料速率 (t/h)


class WebConfig:
    """仿真步长、皮带几何、物理参数、预测与 HTTP 服务等相关常量。"""

    DT = 1.0
    LOG_INTERVAL_SEC = 3.0

    # ── 皮带物理参数（来自 0756/app.py BeltConfig） ──────────────────

    BELT_MAIN = BeltConfig(
        id="main",
        name="主运大巷皮带",
        length=5000.0,
        cell_length=1.0,
        min_speed=1.5,
        max_speed=4.5,
        max_density=0.125,
        empty_mass_kg_m=78.0,
        resistance=0.032,
        efficiency=0.92,
        lift_m=0.0,
        aux_kw=16.0,
        wear_speed=0.050,
        wear_load=0.022,
        wear_ramp=0.80,
    )

    BELT_INCLINE = BeltConfig(
        id="incline",
        name="主斜井皮带",
        length=1160.0,
        cell_length=1.0,
        min_speed=1.5,
        max_speed=4.5,
        max_density=0.111,
        empty_mass_kg_m=72.0,
        resistance=0.034,
        efficiency=0.90,
        lift_m=340.0,
        aux_kw=12.0,
        wear_speed=0.060,
        wear_load=0.028,
        wear_ramp=0.90,
    )

    BELT_PANEL101 = BeltConfig(
        id="panel101",
        name="101皮带",
        length=147.0,
        cell_length=1.0,
        min_speed=1.5,
        max_speed=4.5,
        max_density=0.123,
        empty_mass_kg_m=55.0,
        resistance=0.035,
        efficiency=0.91,
        lift_m=0.0,
        aux_kw=4.0,
        wear_speed=0.045,
        wear_load=0.020,
        wear_ramp=1.00,
    )

    BELT_ORDER = ("main", "incline", "panel101")
    BELT_CONFIGS = {"main": BELT_MAIN, "incline": BELT_INCLINE, "panel101": BELT_PANEL101}

    # ── 转载点与入流 ────────────────────────────────────────────────

    LOAD_POINTS = [
        LoadPointConfig(id="A", name="3306综采", belt="main", pos=0.0, queue="A", max_tph=1500),
        LoadPointConfig(id="B", name="3217综采", belt="main", pos=2500.0, queue="B", max_tph=1200),
    ]
    EXTERNAL_QUEUE_IDS = ("A", "B")

    # 前端显示的两个工作面入流点名称（与 replay 对应）
    FACE_NAMES = ["3306综采@0m", "3217综采@2500m"]
    INFLOW_QUEUES = ["A", "B"]

    # ── 各皮带调速档位（统一 5 档：1.5 ~ 4.5 m/s） ────────────────────

    SPEED_GEARS = [1.5, 2.25, 3.0, 3.75, 4.5]
    # 向后兼容别名
    SPEED_GEARS_MAIN = SPEED_GEARS
    SPEED_GEARS_INCLINE = SPEED_GEARS
    SPEED_GEARS_PANEL101 = SPEED_GEARS

    # ── 预测模型 ────────────────────────────────────────────────────

    DATA_DIR = "data"
    LANE0_DATE = "wangpo_3306_20250917"
    LANE1_DATE = "wangpo_3217_20250917"
    MODEL_DIR = os.path.join(_PROJECT_ROOT, "models", "chronos-2")
    CONTEXT_LENGTH = 360
    PREDICTION_LENGTH = 20
    GAP_THRESHOLD_SEC = 30
    QUANTILE_LEVELS = [0.1, 0.5, 0.9]
    PREDICT_BACKEND = "timesfm"
    # PREDICT_BACKEND = "chronos"
    TIMESFM_MODEL_NAME = os.path.join(_PROJECT_ROOT, "models", "timesfm-2.5-200m-pytorch")

    # ── 日志原始流量上界 (t/采样间隔)，用于两路工作面流量图统一纵轴 ──

    MAX_RAW_TRAFFIC = 2.0
    LANE_FLOW_Y_HEADROOM = 1.25
    LANE_FLOW_YMAX = 1.25

    # ── HTTP 服务 ───────────────────────────────────────────────────

    HOST = "0.0.0.0"
    PORT = 5173

    # ── 历史记录与降采样 ────────────────────────────────────────────

    N_STATE_STEPS = 50
    N_HISTORY = 200
    # 主运皮带沿程图 API 降采样：每 N 个 1m 格取 1 点（仿真仍为 1m/格）
    BELT_DOWNSAMPLE = 25

    # ── CSV 输出 ───────────────────────────────────────────────────

    CSV_WRITE_INTERVAL = 10.0  # 调速事件 CSV 写入节流间隔 (s)
    SPEED_EVENTS_CSV = os.path.join("logs", "speed_events.csv")

    @classmethod
    def validate(cls):
        """校验配置参数合理性，异常时抛出 ValueError。"""
        for bid in cls.BELT_ORDER:
            cfg = cls.BELT_CONFIGS[bid]
            if cfg.min_speed >= cfg.max_speed:
                raise ValueError(f"皮带 {bid}: min_speed ({cfg.min_speed}) 必须小于 max_speed ({cfg.max_speed})")
            if cfg.length <= 0:
                raise ValueError(f"皮带 {bid}: length 必须为正数")
            if not (0 < cfg.efficiency <= 1.0):
                raise ValueError(f"皮带 {bid}: efficiency 必须在 (0, 1] 范围内")
            if cfg.max_density <= 0:
                raise ValueError(f"皮带 {bid}: max_density 必须为正数")
            if cfg.cell_length <= 0:
                raise ValueError(f"皮带 {bid}: cell_length 必须为正数")
        if cls.DT <= 0:
            raise ValueError("DT 必须为正数")
        if cls.LOG_INTERVAL_SEC <= 0:
            raise ValueError("LOG_INTERVAL_SEC 必须为正数")

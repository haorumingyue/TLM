"""Web 仿真与仪表盘专用配置（与历史桌面版配置分离，便于单独调参）。
物理参数来源：0756/app.py BeltConfig，三条皮带级联布局。
"""
import os


class WebConfig:
    """仿真步长、皮带几何、物理参数、预测与 HTTP 服务等相关常量。"""

    DT = 1.0
    LOG_INTERVAL_SEC = 3.0

    # ── 皮带物理参数（来自 0756/app.py BeltConfig） ──────────────────

    BELT_MAIN = {
        "id": "main",
        "name": "主运大巷皮带",
        "length": 5000.0,
        "cell_length": 1.0,
        "min_speed": 1.5,
        "max_speed": 4.5,
        "max_density": 0.125,
        "empty_mass_kg_m": 78.0,
        "resistance": 0.032,
        "efficiency": 0.92,
        "lift_m": 0.0,
        "aux_kw": 16.0,
        "wear_speed": 0.050,
        "wear_load": 0.022,
        "wear_ramp": 0.80,
    }

    BELT_INCLINE = {
        "id": "incline",
        "name": "主斜井皮带",
        "length": 1160.0,
        "cell_length": 1.0,
        "min_speed": 1.5,
        "max_speed": 4.5,
        "max_density": 0.111,
        "empty_mass_kg_m": 72.0,
        "resistance": 0.034,
        "efficiency": 0.90,
        "lift_m": 340.0,
        "aux_kw": 12.0,
        "wear_speed": 0.060,
        "wear_load": 0.028,
        "wear_ramp": 0.90,
    }

    BELT_PANEL101 = {
        "id": "panel101",
        "name": "101皮带",
        "length": 147.0,
        "cell_length": 1.0,
        "min_speed": 1.5,
        "max_speed": 4.5,
        "max_density": 0.123,
        "empty_mass_kg_m": 55.0,
        "resistance": 0.035,
        "efficiency": 0.91,
        "lift_m": 0.0,
        "aux_kw": 4.0,
        "wear_speed": 0.045,
        "wear_load": 0.020,
        "wear_ramp": 1.00,
    }

    BELT_ORDER = ("main", "incline", "panel101")
    BELT_CONFIGS = {"main": BELT_MAIN, "incline": BELT_INCLINE, "panel101": BELT_PANEL101}

    # ── 转载点与入流 ────────────────────────────────────────────────

    LOAD_POINTS = [
        {"id": "A", "name": "3306综采", "belt": "main", "pos": 0.0, "queue": "A", "max_tph": 1500},
        {"id": "B", "name": "3217综采", "belt": "main", "pos": 2500.0, "queue": "B", "max_tph": 1200},
    ]
    EXTERNAL_QUEUE_IDS = ("A", "B")

    # 前端显示的两个工作面入流点名称（与 replay 对应）
    FACE_NAMES = ["3306综采@0m", "3217综采@2500m"]
    INFLOW_QUEUES = ["A", "B"]

    # ── 各皮带调速档位（统一 5 档：1.5 ~ 4.5 m/s） ────────────────────

    SPEED_GEARS_MAIN = [1.5, 2.25, 3.0, 3.75, 4.5]
    SPEED_GEARS_INCLINE = [1.5, 2.25, 3.0, 3.75, 4.5]
    SPEED_GEARS_PANEL101 = [1.5, 2.25, 3.0, 3.75, 4.5]

    # ── 预测模型 ────────────────────────────────────────────────────

    DATA_DIR = "data"
    LANE0_DATE = "20250512"
    LANE1_DATE = "20250514"
    MODEL_DIR = os.path.join(os.getcwd(), "models", "chronos-2")
    CONTEXT_LENGTH = 60
    PREDICTION_LENGTH = 10
    GAP_THRESHOLD_SEC = 30
    QUANTILE_LEVELS = [0.1, 0.5, 0.9]
    PREDICT_BACKEND = "timesfm"
    TIMESFM_MODEL_NAME = os.path.join(os.getcwd(), "models", "timesfm-2.5-200m-pytorch")

    # ── 日志原始流量上界 (t/采样间隔)，用于两路工作面流量图统一纵轴 ──

    MAX_RAW_TRAFFIC = 1.66
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

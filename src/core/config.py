"""Web 监控版专用配置（与桌面版 `coal_conveyor.config` 独立，便于分别调参）。"""
import os


class WebConfig:
    BELT_LENGTH = 5000
    CELL_SIZE = 1.0
    DT = 0.1
    INFLOW_POSITIONS = [0, 1000]
    FACE_NAMES = ["3306综采@0m", "3217综采@1000m"]
    # 额定带速（最高档），对应约 4500 t/h
    ACTUAL_SPEED = 4.5
    # 离散调速档位（从低到高，单位 m/s），智能调速时实际带速仅取这些值
    SPEED_GEARS = [1.5, 2.25, 3.0, 3.75, 4.5]
    # 档位切换时的中点回差，使用档间中点做简单滞回避免频繁抖动
    DATA_DIR = "data"
    LANE0_DATE = "20250512"
    LANE1_DATE = "20250514"
    LOG_INTERVAL_SEC = 3.0
    # 日志原始流量上界 (t/采样间隔)，用于两路工作面流量图统一纵轴
    MAX_RAW_TRAFFIC = 1.66
    LANE_FLOW_Y_HEADROOM = 1.25
    MODEL_DIR = os.path.join(os.getcwd(), "models", "chronos-2")
    CONTEXT_LENGTH = 60
    PREDICTION_LENGTH = 10
    GAP_THRESHOLD_SEC = 30
    QUANTILE_LEVELS = [0.1, 0.5, 0.9]
    # 预测模型后端：'chronos' 使用 Chronos2Pipeline；'timesfm' 使用 TimesFM 进行分位数预测
    PREDICT_BACKEND = "chronos"
    # PREDICT_BACKEND = "timesfm"
    # TimesFM 2.5 torch 版本的预训练权重（当 PREDICT_BACKEND='timesfm' 时使用）
    TIMESFM_MODEL_NAME = os.path.join(os.getcwd(), "models", "timesfm-2.5-200m-pytorch")
    HOST = "0.0.0.0"
    PORT = 5173
    N_STATE_STEPS = 50
    N_HISTORY = 200
    BELT_DOWNSAMPLE = 10

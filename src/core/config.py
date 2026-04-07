"""Web 仿真与仪表盘专用配置（与历史桌面版配置分离，便于单独调参）。"""
import os


class WebConfig:
    """仿真步长、皮带几何、离散档位、预测与 HTTP 服务等相关常量。"""
    BELT_LENGTH = 5000
    CELL_SIZE = 1.0
    DT = 0.1
    INFLOW_POSITIONS = [0, 1000]
    FACE_NAMES = ["3306综采@0m", "3217综采@1000m"]
    # 额定带速（最高档），对应约 4500 t/h
    ACTUAL_SPEED = 4.5
    # 离散调速档位（从低到高，m/s）；换挡时在相邻档中点滞回，见 Simulator._apply_gears
    SPEED_GEARS = [1.5, 2.25, 3.0, 3.75, 4.5]
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

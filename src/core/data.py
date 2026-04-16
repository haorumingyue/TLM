"""历史流量日志解析：正则抽取、断点检测、单位换算（日志间隔 → t/s）。"""
import os
import re

import numpy as np
import pandas as pd

from .config import WebConfig
from .logging_config import get_logger

log = get_logger(__name__)


_LOG_PATTERN = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.\d+:\s+流量:\s+"
    r"(?P<val>[0-9]+(?:\.[0-9]*)?|None)"
)
_VEL_PATTERN = re.compile(
    r"速度:\s+(?P<vel>[0-9]+(?:\.[0-9]*)?|None)"
)


def parse_file(filepath: str) -> pd.DataFrame:
    """按行解析「时间戳 + 流量 + 速度」文本，缺失值线性插值后返回 DataFrame。"""
    timestamps, values, velocities = [], [], []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            m = _LOG_PATTERN.search(line)
            if m:
                timestamps.append(m.group(1))
                v = m.group("val")
                try:
                    values.append(float(v))
                except (ValueError, TypeError):
                    values.append(np.nan)

                vm = _VEL_PATTERN.search(line)
                if vm:
                    vv = vm.group("vel")
                    try:
                        velocities.append(float(vv))
                    except (ValueError, TypeError):
                        velocities.append(np.nan)
                else:
                    velocities.append(np.nan)
    df = pd.DataFrame({"timestamp": timestamps, "traffic": values, "velocity": velocities})
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["traffic"] = df["traffic"].interpolate(method="linear").bfill().ffill()
    df["velocity"] = df["velocity"].interpolate(method="linear").bfill().ffill()
    return df


def load_file(data_dir: str, date_str: str) -> pd.DataFrame:
    """加载 `{date_str}.txt` 日志并调用 parse_file。"""
    fp = os.path.join(data_dir, f"{date_str}.txt")
    if not os.path.exists(fp):
        raise FileNotFoundError(f"日志文件不存在: {fp}")
    log.info("  ✅ 加载文件: %s", os.path.basename(fp))
    return parse_file(fp)


def build_break_mask(timestamps, gap_sec=WebConfig.GAP_THRESHOLD_SEC) -> np.ndarray:
    """相邻时间戳间隔超过 gap_sec 视为断点（停机/换班），用于回放时清零入流。"""
    ts = pd.to_datetime(timestamps)
    diffs = pd.Series(ts).diff().dt.total_seconds().fillna(0).values
    return diffs > gap_sec


def raw2ts(v):
    """将日志按间隔累计的流量（t/采样间隔）换算为 t/s。"""
    return v / WebConfig.LOG_INTERVAL_SEC


__all__ = ["load_file", "build_break_mask", "raw2ts"]

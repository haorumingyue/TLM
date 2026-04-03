import os
import re

import numpy as np
import pandas as pd

from .config import WebConfig


_LOG_PATTERN = re.compile(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.\d+:\s+流量:\s+"
    r"([0-9\.]+None|None|[0-9\.]+)"
)


def parse_file(filepath: str) -> pd.DataFrame:
    timestamps, values = [], []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            m = _LOG_PATTERN.search(line)
            if m:
                timestamps.append(m.group(1))
                v = m.group(2)
                try:
                    values.append(float(v))
                except (ValueError, TypeError):
                    values.append(np.nan)
    df = pd.DataFrame({"timestamp": timestamps, "traffic": values})
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["traffic"] = df["traffic"].interpolate(method="linear").bfill().ffill()
    return df


def load_file(data_dir: str, date_str: str) -> pd.DataFrame:
    fp = os.path.join(data_dir, f"{date_str}.txt")
    if not os.path.exists(fp):
        raise FileNotFoundError(f"日志文件不存在: {fp}")
    print(f"  ✅ 加载文件: {os.path.basename(fp)}")
    return parse_file(fp)


def build_break_mask(timestamps, gap_sec=WebConfig.GAP_THRESHOLD_SEC) -> np.ndarray:
    ts = pd.to_datetime(timestamps)
    diffs = pd.Series(ts).diff().dt.total_seconds().fillna(0).values
    return diffs > gap_sec


def raw2ts(v):
    """t/3s -> t/s"""
    return v / WebConfig.LOG_INTERVAL_SEC


__all__ = ["load_file", "build_break_mask", "raw2ts"]

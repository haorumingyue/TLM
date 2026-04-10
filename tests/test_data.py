"""data.py 数据解析与断点检测单元测试。"""
import os
import tempfile

import numpy as np
import pandas as pd
import pytest

from src.core.data import parse_file, build_break_mask, raw2ts
from src.core.config import WebConfig


class TestParseFile:
    def _write_log(self, tmp_dir, lines):
        fp = os.path.join(tmp_dir, "test.txt")
        with open(fp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return fp

    def test_basic_parse(self, tmp_path):
        lines = [
            "2025-05-12 08:00:00.123: 流量: 1.5",
            "2025-05-12 08:00:03.456: 流量: 2.0",
            "2025-05-12 08:00:06.789: 流量: 0.8",
        ]
        fp = self._write_log(str(tmp_path), lines)
        df = parse_file(fp)
        assert len(df) == 3
        assert list(df.columns) == ["timestamp", "traffic"]
        assert df["traffic"].iloc[0] == pytest.approx(1.5)
        assert df["traffic"].iloc[1] == pytest.approx(2.0)

    def test_none_value_interpolated(self, tmp_path):
        lines = [
            "2025-05-12 08:00:00.000: 流量: 1.0",
            "2025-05-12 08:00:03.000: 流量: None",
            "2025-05-12 08:00:06.000: 流量: 3.0",
        ]
        fp = self._write_log(str(tmp_path), lines)
        df = parse_file(fp)
        assert len(df) == 3
        # None 应被线性插值为 2.0
        assert df["traffic"].iloc[1] == pytest.approx(2.0)

    def test_empty_file(self, tmp_path):
        fp = self._write_log(str(tmp_path), ["no matching lines here"])
        df = parse_file(fp)
        assert len(df) == 0


class TestBuildBreakMask:
    def test_no_breaks(self):
        ts = pd.to_datetime(["2025-05-12 08:00:00", "2025-05-12 08:00:03", "2025-05-12 08:00:06"])
        mask = build_break_mask(ts.values)
        assert mask.sum() == 0

    def test_break_detected(self):
        ts = pd.to_datetime(["2025-05-12 08:00:00", "2025-05-12 08:05:00", "2025-05-12 08:05:03"])
        mask = build_break_mask(ts.values, gap_sec=30)
        assert mask[1] == True  # 5 分钟间隔 > 30s
        assert mask[2] == False

    def test_custom_threshold(self):
        ts = pd.to_datetime(["2025-05-12 08:00:00", "2025-05-12 08:00:10"])
        mask = build_break_mask(ts.values, gap_sec=5)
        assert mask[1] == True
        mask2 = build_break_mask(ts.values, gap_sec=15)
        assert mask2[1] == False


class TestRaw2Ts:
    def test_conversion(self):
        result = raw2ts(3.0)
        assert result == pytest.approx(3.0 / WebConfig.LOG_INTERVAL_SEC)

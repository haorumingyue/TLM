"""Predictor mock 单元测试（不依赖真实模型权重）。"""
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from src.predict.predictor import Predictor
from src.core.config import WebConfig


class TestPredictor:
    def test_not_ready_before_load(self):
        pred = Predictor()
        assert pred.ready is False

    def test_predict_returns_none_when_not_ready(self):
        pred = Predictor()
        result = pred.predict(np.ones(60))
        assert result is None

    @patch("src.predict.predictor.Predictor._load_chronos")
    def test_chronos_load_sets_ready(self, mock_load):
        pred = Predictor()
        pred._pipe = MagicMock()  # 模拟已加载
        assert pred.ready is True

    @patch("src.predict.predictor.Predictor._load_chronos")
    def test_predict_with_mock_chronos(self, mock_load):
        pred = Predictor()
        mock_pipe = MagicMock()
        # 模拟 predict_quantiles 返回
        fake_q = np.random.rand(1, 1, WebConfig.PREDICTION_LENGTH, 3)
        mock_pipe.predict_quantiles.return_value = (
            [MagicMock(squeeze=MagicMock(return_value=MagicMock(
                numpy=MagicMock(return_value=np.random.rand(WebConfig.PREDICTION_LENGTH, 3))
            )))],
            None,
        )
        pred._pipe = mock_pipe
        WebConfig.PREDICT_BACKEND = "chronos"
        try:
            result = pred.predict(np.ones(WebConfig.CONTEXT_LENGTH))
            assert result is not None
            q_low, q_med, q_high = result
            assert len(q_low) == WebConfig.PREDICTION_LENGTH
        finally:
            WebConfig.PREDICT_BACKEND = "timesfm"

    def test_timesfm_ready_flag(self):
        pred = Predictor()
        pred._timesfm = MagicMock()
        assert pred.ready is True

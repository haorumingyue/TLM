import threading

import numpy as np
import torch

from ..core.config import WebConfig


class Predictor:
    def __init__(self):
        self._pipe = None
        self._lock = threading.Lock()

    def load(self):
        from chronos import Chronos2Pipeline

        with self._lock:
            if self._pipe:
                return
            try:
                self._pipe = Chronos2Pipeline.from_pretrained(WebConfig.MODEL_DIR, device_map="auto")
            except Exception:
                self._pipe = Chronos2Pipeline.from_pretrained(WebConfig.MODEL_DIR, device_map="cpu")
        print("  ✅ Chronos-2 模型加载完成")

    @property
    def ready(self):
        return self._pipe is not None

    def predict(self, ctx):
        if not self.ready:
            return None
        t = torch.tensor(ctx[-WebConfig.CONTEXT_LENGTH :], dtype=torch.float32)
        with self._lock:
            ql, _ = self._pipe.predict_quantiles(
                [t],
                prediction_length=WebConfig.PREDICTION_LENGTH,
                quantile_levels=WebConfig.QUANTILE_LEVELS,
            )
        q = ql[0].squeeze(0).numpy()
        return q[:, 0], q[:, 1], q[:, 2]

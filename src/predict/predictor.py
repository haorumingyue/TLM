"""时序预测封装：Chronos-2 或 TimesFM，输出未来步长的分位数流量。"""
import threading

import numpy as np
import torch

from ..core.config import WebConfig
from ..core.logging_config import get_logger

log = get_logger(__name__)


class Predictor:
    """懒加载模型；predict 返回 (q_low, q_med, q_high) 与未来步对齐。"""

    def __init__(self):
        self._pipe = None
        self._timesfm = None
        self._lock = threading.Lock()

    def load(self):
        """按 WebConfig.PREDICT_BACKEND 加载权重；TimesFM 失败时可回退 Chronos。"""
        with self._lock:
            if self._pipe or self._timesfm:
                return

            backend = str(getattr(WebConfig, "PREDICT_BACKEND", "chronos")).lower()
            if backend == "timesfm":
                try:
                    self._load_timesfm()
                    log.info("✅ TimesFM 模型加载完成")
                except Exception as e:
                    log.warning("⚠️ TimesFM 加载失败，回退到 Chronos-2：%s", e)
                    self._load_chronos()
                    log.info("✅ Chronos-2 模型加载完成")
            else:
                self._load_chronos()
                log.info("✅ Chronos-2 模型加载完成")

    def _load_chronos(self):
        from chronos import Chronos2Pipeline

        self._pipe = Chronos2Pipeline.from_pretrained(
            WebConfig.MODEL_DIR, device_map="cuda"
        )

    def _load_timesfm(self):
        """
        TimesFM 分位数输出格式（use_continuous_quantile_head=True）：
        quantile_forecast: (batch, horizon, 10) = [mean, q0.1, q0.2, ..., q0.9]
        """
        import sys

        try:
            import timesfm  # noqa: F401
        except ImportError as e:
            # 这里不做"自动安装"，因为 timesfm 在不同 Python 版本上有硬约束，
            # 自动安装会反复触发依赖/版本冲突（例如 Python 3.13 不支持）。
            v = sys.version_info
            raise RuntimeError(
                "TimesFM 需要在兼容的 Python 环境安装后再运行。\n"
                f"- 当前 Python: {v.major}.{v.minor}.{v.micro}\n"
                "建议：新建 Python=3.10~3.12 的虚拟环境，然后在该环境里执行：\n"
                "  git clone https://github.com/google-research/timesfm.git\n"
                "  cd timesfm\n"
                "  pip install -e .[torch]\n"
            ) from e

        # 以 PyTorch 后端为例（与官方 TimesFM 2.5 torch 类一致）
        model_cls = getattr(timesfm, "TimesFM_2p5_200M_torch")

        # 兼容性处理：
        # 某些 huggingface_hub 版本下，from_pretrained() 可能会把 `proxies`
        # 作为额外 keyword 透传到 TimesFM 的 __init__，而该 __init__ 并不接收 proxies。
        # 因此这里优先走 _from_pretrained，并强制 local_files_only=True 以使用本地目录权重。
        try:
            model = model_cls.from_pretrained(WebConfig.TIMESFM_MODEL_NAME, torch_compile=True)
        except TypeError as e:
            if "proxies" not in str(e).lower():
                raise
            model = model_cls._from_pretrained(
                model_id=WebConfig.TIMESFM_MODEL_NAME,
                revision=None,
                cache_dir=None,
                force_download=False,
                local_files_only=True,
                token=None,
                config=None,
                torch_compile=True,
            )

        model.compile(
            timesfm.ForecastConfig(
                max_context=WebConfig.CONTEXT_LENGTH,
                max_horizon=WebConfig.PREDICTION_LENGTH,
                normalize_inputs=True,
                use_continuous_quantile_head=True,
                force_flip_invariance=True,
                infer_is_positive=True,
                fix_quantile_crossing=True,
                return_backcast=True,
            )
        )
        self._timesfm = model

    @property
    def ready(self):
        # 允许"TimesFM加载失败回退Chronos"时仍正常工作
        return (self._timesfm is not None) or (self._pipe is not None)

    @property
    def supports_covariates(self):
        """当前后端是否支持协变量预测（两个后端均支持）。"""
        return (self._timesfm is not None) or (self._pipe is not None)

    def predict(self, ctx, covariates=None):
        """
        ctx: 最近 CONTEXT_LENGTH 个采样点的流量序列。
        covariates: dict，键为协变量名，值为长度 >= len(ctx) + PREDICTION_LENGTH 的序列。
                    例如 {"velocity": vel_series}。
        返回三组与未来 horizon 等长的数组 (q_low, q_med, q_high)。
        """
        if not self.ready:
            return None

        backend = str(getattr(WebConfig, "PREDICT_BACKEND", "chronos")).lower()
        tail = np.asarray(ctx[-WebConfig.CONTEXT_LENGTH :], dtype=np.float32)

        with self._lock:
            if backend == "timesfm" and self._timesfm is not None:
                if covariates and self.supports_covariates:
                    result = self._predict_timesfm_with_covariates(tail, covariates)
                else:
                    result = self._predict_timesfm(tail)
            elif self._pipe is not None:
                if covariates:
                    result = self._predict_chronos_with_covariates(tail, covariates)
                else:
                    t = torch.tensor(tail, dtype=torch.float32, device="cuda")
                    ql, _ = self._pipe.predict_quantiles(
                        [t],
                        prediction_length=WebConfig.PREDICTION_LENGTH,
                        quantile_levels=WebConfig.QUANTILE_LEVELS,
                    )
                    q = ql[0].squeeze(0).cpu().numpy()
                    result = q[:, 0], q[:, 1], q[:, 2]
            else:
                return None

            # 流量不能为负数
            return np.maximum(result[0], 0.0), np.maximum(result[1], 0.0), np.maximum(result[2], 0.0)

    def _predict_timesfm(self, tail):
        """纯单变量 TimesFM 预测。"""
        point_forecast, quantile_forecast = self._timesfm.forecast(
            horizon=WebConfig.PREDICTION_LENGTH, inputs=[tail]
        )
        q = quantile_forecast[0]  # (horizon, 10)
        q_low = q[:, 1]  # 0.1
        q_med = q[:, 5]  # 0.5
        q_high = q[:, 9]  # 0.9
        return q_low, q_med, q_high

    def _predict_timesfm_with_covariates(self, tail, covariates):
        """TimesFM + XReg 协变量预测。

        forecast_with_covariates 返回:
          point_outputs: list[ndarray (horizon,)]
          quantile_outputs: list[ndarray (horizon, 9)]  — 9 个分位数 [0.1..0.9]
        """
        cov_dict = {}
        for name, series in covariates.items():
            arr = np.asarray(series, dtype=np.float32)
            need_len = WebConfig.CONTEXT_LENGTH + WebConfig.PREDICTION_LENGTH
            if len(arr) < need_len:
                pad = np.full(need_len - len(arr), arr[-1] if len(arr) > 0 else 0.0, dtype=np.float32)
                arr = np.concatenate([arr, pad])
            cov_dict[name] = [arr[:need_len]]

        point_forecast, quantile_forecast = self._timesfm.forecast_with_covariates(
            inputs=[tail],
            dynamic_numerical_covariates=cov_dict,
            xreg_mode="xreg + timesfm",
            normalize_xreg_target_per_input=True,
        )
        # quantile_forecast: list of ndarray, 每个 (horizon, 9)
        # 分位数顺序: [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
        q = quantile_forecast[0]  # (horizon, 9)
        q_low = q[:, 0]   # 0.1
        q_med = q[:, 4]   # 0.5
        q_high = q[:, 8]  # 0.9
        return q_low, q_med, q_high

    def _predict_chronos_with_covariates(self, tail, covariates):
        """Chronos-2 协变量预测（dict 格式 inputs: target + past/future_covariates）。"""
        past_cov = {}
        future_cov = {}
        for name, series in covariates.items():
            arr = np.asarray(series, dtype=np.float32)
            need_len = WebConfig.CONTEXT_LENGTH + WebConfig.PREDICTION_LENGTH
            if len(arr) < need_len:
                pad = np.full(need_len - len(arr), arr[-1] if len(arr) > 0 else 0.0, dtype=np.float32)
                arr = np.concatenate([arr, pad])
            arr = arr[:need_len]
            past_cov[name] = torch.tensor(arr[:WebConfig.CONTEXT_LENGTH], dtype=torch.float32, device="cuda")
            future_cov[name] = torch.tensor(arr[WebConfig.CONTEXT_LENGTH:], dtype=torch.float32, device="cuda")

        task = {
            "target": torch.tensor(tail, dtype=torch.float32, device="cuda"),
            "past_covariates": past_cov,
            "future_covariates": future_cov,
        }
        ql, _ = self._pipe.predict_quantiles(
            [task],
            prediction_length=WebConfig.PREDICTION_LENGTH,
            quantile_levels=WebConfig.QUANTILE_LEVELS,
        )
        # 输出 shape: (n_variates, prediction_length, n_quantiles)
        # variate 0 = target 预测，后面的 variate 是协变量的预测（无意义）
        q = ql[0][0].cpu().numpy()
        return q[:, 0], q[:, 1], q[:, 2]

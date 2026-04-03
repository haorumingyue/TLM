import os
import subprocess
import sys
import threading
import warnings

warnings.filterwarnings("ignore")


def _ensure_deps():
    try:
        import flask  # noqa: F401
        import pandas  # noqa: F401
        import torch  # noqa: F401
        from chronos import Chronos2Pipeline  # noqa: F401
    except ImportError:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "flask", "chronos-forecasting", "pandas", "torch"]
        )
        os.execv(sys.executable, ["python"] + sys.argv)


_ensure_deps()

from .app import create_app
from ..core.config import WebConfig
from ..core.data import build_break_mask, load_file
from ..predict.predictor import Predictor
from .replay import Replay
from .runtime import WebRuntime, sim_thread
from . import runtime as rt
from ..core.simulator import Simulator
from ..core.state import SimState


def main():
    print("=" * 56)
    print("  主煤流协同控制系统 — Web 仿真与监控")
    print("=" * 56)

    print("\n📂 加载日志数据...")
    df0 = load_file(WebConfig.DATA_DIR, WebConfig.LANE0_DATE)
    df1 = load_file(WebConfig.DATA_DIR, WebConfig.LANE1_DATE)
    ib0 = build_break_mask(df0["timestamp"].values)
    ib1 = build_break_mask(df1["timestamp"].values)
    print(f"  Lane0: {len(df0)} 条, 断点 {int(ib0.sum())} 处")
    print(f"  Lane1: {len(df1)} 条, 断点 {int(ib1.sum())} 处")

    print("\n🤖 初始化 Chronos-2 预测器（后台加载）...")
    runtime = WebRuntime()
    runtime.pred = Predictor()
    runtime.sim = Simulator()
    runtime.sim_const = Simulator(fixed_speed=WebConfig.ACTUAL_SPEED)
    runtime.replay = Replay([df0, df1], [ib0, ib1], runtime.sim, runtime.pred)
    runtime.state = SimState()

    rt.ctx = runtime

    threading.Thread(target=runtime.pred.load, daemon=True).start()
    threading.Thread(target=sim_thread, daemon=True).start()

    app = create_app()
    print(f"\n🌐 仪表盘已启动 → 浏览器打开: http://localhost:{WebConfig.PORT}")
    print("   Ctrl+C 退出\n")
    app.run(host=WebConfig.HOST, port=WebConfig.PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()

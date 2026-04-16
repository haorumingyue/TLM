"""命令行入口：校验依赖、加载数据、启动预测加载线程与仿真线程、运行 Flask。"""
import sys
import threading
import warnings

from ..core.logging_config import setup_logging, get_logger

warnings.filterwarnings("ignore")
setup_logging()
log = get_logger(__name__)


def _check_deps():
    """检查核心依赖是否已安装，缺失时输出友好提示并退出。"""
    missing = []
    for pkg, imp in [("flask", "flask"), ("pandas", "pandas"), ("torch", "torch"),
                     ("chronos-forecasting", "chronos")]:
        try:
            __import__(imp)
        except ImportError:
            missing.append(pkg)
    if missing:
        log.error("缺少以下依赖，请手动安装后重试: %s", ' '.join(missing))
        print(f"   pip install {' '.join(missing)}")
        sys.exit(1)


_check_deps()

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

    WebConfig.validate()

    log.info("📂 加载日志数据...")
    df0 = load_file(WebConfig.DATA_DIR, WebConfig.LANE0_DATE)
    df1 = load_file(WebConfig.DATA_DIR, WebConfig.LANE1_DATE)
    ib0 = build_break_mask(df0["timestamp"].values)
    ib1 = build_break_mask(df1["timestamp"].values)
    log.info("  Lane0: %d 条, 断点 %d 处", len(df0), int(ib0.sum()))
    log.info("  Lane1: %d 条, 断点 %d 处", len(df1), int(ib1.sum()))

    log.info("🤖 初始化预测器（后台加载）...")
    runtime = WebRuntime()
    runtime.pred = Predictor()
    runtime.sim = Simulator()
    runtime.sim_const = Simulator(fixed_speed=True)
    runtime.replay = Replay(
        [df0, df1], [ib0, ib1], runtime.sim, runtime.pred, sim_const=runtime.sim_const
    )
    runtime.state = SimState()

    rt.ctx = runtime

    threading.Thread(target=runtime.pred.load, daemon=True).start()
    threading.Thread(target=sim_thread, daemon=True).start()

    app = create_app()
    log.info("🌐 仪表盘已启动 → http://localhost:%d", WebConfig.PORT)
    log.info("   Ctrl+C 退出")
    app.run(host=WebConfig.HOST, port=WebConfig.PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()

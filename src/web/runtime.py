"""全局仿真上下文与后台线程：按日志节拍推进双仿真并刷新状态快照。"""
import time

from ..core.config import WebConfig

ctx = None


def sim_thread():
    """后台无限循环：未暂停时按日志周期推进双仿真并更新 SimState。"""
    global ctx
    dt = WebConfig.DT
    log_iv = WebConfig.LOG_INTERVAL_SEC
    steps_per_log_tick = max(1, int(round(log_iv / dt)))
    n = 0
    while True:
        if ctx is None:
            time.sleep(0.1)
            continue
        if ctx.state.paused:
            time.sleep(0.05)
            continue

        # 一个日志采样周期：先推进 log_iv 对应的若干 DT 步，再等待本周期内两路预测队列清空
        for _ in range(steps_per_log_tick):
            ctx.replay.update(ctx.sim.time)
            ctx.sim.auto = ctx.state.auto_speed
            ctx.sim.step()
            for i in range(2):
                ctx.sim_const.set_rate(i, ctx.sim.rates[i])
            ctx.sim_const.step()
            n += 1
            if n % WebConfig.N_STATE_STEPS == 0:
                ctx.state.snapshot(ctx.sim, ctx.sim_const, ctx.replay, ctx.pred)

        ctx.replay.wait_for_pending_predictions()
        ctx.state.snapshot(ctx.sim, ctx.sim_const, ctx.replay, ctx.pred)


class WebRuntime:
    """聚合 AI 工况仿真、额定对照仿真、回放与预测器、SimState。"""

    __slots__ = ("sim", "sim_const", "replay", "pred", "state")

    def __init__(self):
        self.sim = self.sim_const = self.replay = self.pred = self.state = None

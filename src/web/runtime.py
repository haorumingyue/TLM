import time

from ..core.config import WebConfig

ctx = None


def sim_thread():
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

        # 一个「日志时间点」：推进 log_iv 秒仿真时间（多步 DT），再等待本周期内已入队的预测全部完成
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
    __slots__ = ("sim", "sim_const", "replay", "pred", "state")

    def __init__(self):
        self.sim = self.sim_const = self.replay = self.pred = self.state = None

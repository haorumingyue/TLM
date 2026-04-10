"""按历史日志驱动仿真入流，并在后台线程中异步提交预测任务。"""
import queue as _queue
import threading
import time

import numpy as np

from ..core.config import WebConfig
from ..core.data import raw2ts


class Replay:
    """双路日志索引、断点处理、预测队列与缓存，供 Simulator.pred_flows 使用前馈。"""

    def __init__(self, dfs, masks, sim, pred, sim_const=None):
        self.dfs = dfs
        self.masks = masks
        self.sim = sim
        self.pred = pred
        # 额定常速对照仿真：与工作面入流同一时间轴绑定（避免仅事后拷贝 rates 产生偏差）
        self.sim_const = sim_const
        self.idx = [0, 0]
        self.buf = [[], []]
        self.cache = [None, None]
        self.pred_buf = [{}, {}]
        self._q = [_queue.Queue(), _queue.Queue()]
        self.q_size = [0, 0]
        for lane in range(2):
            threading.Thread(target=self._worker, args=(lane,), daemon=True).start()

    def _worker(self, lane):
        q = self._q[lane]
        while True:
            ctx, ptr = q.get()
            try:
                self.q_size[lane] = q.qsize()
                while not self.pred.ready:
                    time.sleep(0.2)
                r = self.pred.predict(ctx)
                if r:
                    lo, md, hi = r
                    ft = np.arange(ptr + 1, ptr + 1 + WebConfig.PREDICTION_LENGTH) * WebConfig.LOG_INTERVAL_SEC
                    self.cache[lane] = (ft, raw2ts(lo), raw2ts(md), raw2ts(hi))
                    self.pred_buf[lane][ptr + 1] = round(float(raw2ts(md[0])), 4)
                    keep = max(0, ptr - WebConfig.N_HISTORY * 2)
                    self.pred_buf[lane] = {k: v for k, v in self.pred_buf[lane].items() if k >= keep}
            finally:
                q.task_done()

    def wait_for_pending_predictions(self):
        """等待两路预测队列中已提交任务全部推理完成（线程内 predict 返回并 task_done）。"""
        self._q[0].join()
        self._q[1].join()

    def _set_lane_rate_both(self, lane, rate_t_per_s):
        """两工作面入流同时写入智能仿真与额定常速对照仿真。"""
        self.sim.set_rate(lane, rate_t_per_s)
        if self.sim_const is not None:
            self.sim_const.set_rate(lane, rate_t_per_s)

    def update(self, t):
        ei = int(t / WebConfig.LOG_INTERVAL_SEC)
        for lane in range(2):
            df = self.dfs[lane]
            ib = self.masks[lane]
            while self.idx[lane] < ei and self.idx[lane] < len(df) - 1:
                i = self.idx[lane]
                if i > 0 and ib[i]:
                    self._set_lane_rate_both(lane, 0.0)
                    self.buf[lane] = []
                    self.cache[lane] = None
                    self.sim.pred_flows[lane] = None
                else:
                    raw = float(df["traffic"].iloc[i])
                    self._set_lane_rate_both(lane, raw2ts(raw))
                    self.buf[lane].append(raw)
                    if len(self.buf[lane]) > WebConfig.CONTEXT_LENGTH:
                        self.buf[lane] = self.buf[lane][-WebConfig.CONTEXT_LENGTH :]
                    if len(self.buf[lane]) >= WebConfig.CONTEXT_LENGTH:
                        self._q[lane].put((np.array(self.buf[lane]), self.idx[lane]))
                self.idx[lane] += 1
            if self.cache[lane]:
                self.sim.pred_flows[lane] = self.cache[lane][2]

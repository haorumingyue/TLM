import queue as _queue
import threading
import time

import numpy as np

from ..core.config import WebConfig
from ..core.data import raw2ts


class Replay:
    def __init__(self, dfs, masks, sim, pred):
        self.dfs = dfs
        self.masks = masks
        self.sim = sim
        self.pred = pred
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
            q.task_done()

    def wait_for_pending_predictions(self):
        """等待两路预测队列中已提交任务全部推理完成（线程内 predict 返回并 task_done）。"""
        self._q[0].join()
        self._q[1].join()

    def update(self, t):
        ei = int(t / WebConfig.LOG_INTERVAL_SEC)
        for lane in range(2):
            df = self.dfs[lane]
            ib = self.masks[lane]
            while self.idx[lane] < ei and self.idx[lane] < len(df) - 1:
                i = self.idx[lane]
                if i > 0 and ib[i]:
                    self.sim.set_rate(lane, 0.0)
                    self.buf[lane] = []
                    self.cache[lane] = None
                    self.sim.pred_flows[lane] = None
                else:
                    raw = float(df["traffic"].iloc[i])
                    self.sim.set_rate(lane, raw2ts(raw))
                    self.buf[lane].append(raw)
                    if len(self.buf[lane]) > WebConfig.CONTEXT_LENGTH:
                        self.buf[lane] = self.buf[lane][-WebConfig.CONTEXT_LENGTH :]
                    if len(self.buf[lane]) >= WebConfig.CONTEXT_LENGTH:
                        self._q[lane].put((np.array(self.buf[lane]), self.idx[lane]))
                self.idx[lane] += 1
            if self.cache[lane]:
                self.sim.pred_flows[lane] = self.cache[lane][2]

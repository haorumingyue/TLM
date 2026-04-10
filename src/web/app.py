"""Flask 应用：仪表盘页面、/api/state、/api/stream（SSE）与 /api/control。"""
import json
import os
import time

from flask import Flask, Response, jsonify, render_template, request

from . import runtime as rt
from ..core.config import WebConfig


def create_app():
    """注册路由；模板内 lane_flow_ymax 与额定能力一致，便于纵轴统一。"""
    root = os.path.dirname(os.path.abspath(__file__))
    app = Flask(
        __name__,
        template_folder=os.path.join(root, "templates"),
        static_folder=os.path.join(root, "static"),
    )

    @app.route("/")
    def index():
        lane_flow_ymax = WebConfig.LANE_FLOW_YMAX
        return render_template("dashboard.html", lane_flow_ymax=lane_flow_ymax)

    @app.route("/api/state")
    def api_state():
        if rt.ctx is None or rt.ctx.state is None:
            return jsonify({"booting": True})
        d = rt.ctx.state.get()
        if not d:
            return jsonify({"booting": True})
        return jsonify(d)

    @app.route("/api/stream")
    def api_stream():
        """SSE 端点：每秒推送一次仿真状态快照。"""
        def generate():
            try:
                while True:
                    if rt.ctx is None or rt.ctx.state is None:
                        yield "data: {\"booting\": true}\n\n"
                    else:
                        d = rt.ctx.state.get()
                        if d:
                            yield f"data: {json.dumps(d, ensure_ascii=False)}\n\n"
                        else:
                            yield "data: {\"booting\": true}\n\n"
                    time.sleep(1.0)
            except GeneratorExit:
                # 客户端断开连接，干净退出
                return

        return Response(generate(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.route("/api/control", methods=["POST"])
    def api_control():
        if rt.ctx is None or rt.ctx.state is None:
            return jsonify({"ok": False, "error": "service_not_ready"}), 503
        body = request.get_json(silent=True) or {}
        act = body.get("action", "")
        if act == "pause":
            rt.ctx.state.set_control(paused=True)
        elif act == "resume":
            rt.ctx.state.set_control(paused=False)
        elif act == "toggle_vfd":
            paused, auto_speed = rt.ctx.state.get_control()
            rt.ctx.state.set_control(auto_speed=not auto_speed)
        else:
            return jsonify({"ok": False, "error": "unknown_action"}), 400
        paused, auto_speed = rt.ctx.state.get_control()
        return jsonify(
            {
                "ok": True,
                "paused": paused,
                "auto_speed": auto_speed,
            }
        )

    return app

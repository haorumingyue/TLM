import os

from flask import Flask, jsonify, render_template, request

from . import runtime as rt
from ..core.config import WebConfig


def create_app():
    root = os.path.dirname(os.path.abspath(__file__))
    app = Flask(__name__, template_folder=os.path.join(root, "templates"))

    @app.route("/")
    def index():
        # 横坐标上限统一设为 1.25 t/s，即带速 4.5m/s 下 4500 t/h 的最大额定主煤流能力
        lane_flow_ymax = 1.25
        return render_template("dashboard.html", lane_flow_ymax=lane_flow_ymax)

    @app.route("/api/state")
    def api_state():
        if rt.ctx is None or rt.ctx.state is None:
            return jsonify({"booting": True})
        d = rt.ctx.state.get()
        if not d:
            return jsonify({"booting": True})
        return jsonify(d)

    @app.route("/api/control", methods=["POST"])
    def api_control():
        if rt.ctx is None or rt.ctx.state is None:
            return jsonify({"ok": False, "error": "service_not_ready"}), 503
        body = request.get_json(silent=True) or {}
        act = body.get("action", "")
        if act == "pause":
            rt.ctx.state.paused = True
        elif act == "resume":
            rt.ctx.state.paused = False
        elif act == "toggle_vfd":
            rt.ctx.state.auto_speed = not rt.ctx.state.auto_speed
        else:
            return jsonify({"ok": False, "error": "unknown_action"}), 400
        return jsonify(
            {
                "ok": True,
                "paused": rt.ctx.state.paused,
                "auto_speed": rt.ctx.state.auto_speed,
            }
        )

    return app

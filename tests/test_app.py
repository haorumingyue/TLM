"""Flask 路由端到端测试。"""
import json

import pytest

from src.web.app import create_app
from src.web import runtime as rt
from src.web.runtime import WebRuntime
from src.core.state import SimState


@pytest.fixture
def client():
    """创建 Flask 测试客户端。"""
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestAPIRoutes:
    def test_index_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"主煤流协同控制系统" in resp.data

    def test_api_state_booting(self, client):
        """ctx 未初始化时应返回 booting。"""
        rt.ctx = None
        resp = client.get("/api/state")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data.get("booting") is True

    def test_api_state_with_context(self, client):
        """ctx 初始化后应返回仿真数据。"""
        runtime = WebRuntime()
        runtime.state = SimState()
        runtime.state.data = {"sim_time": 42.0}
        rt.ctx = runtime
        try:
            resp = client.get("/api/state")
            assert resp.status_code == 200
            data = json.loads(resp.data)
            assert data.get("sim_time") == 42.0
        finally:
            rt.ctx = None

    def test_api_control_unknown_action(self, client):
        runtime = WebRuntime()
        runtime.state = SimState()
        rt.ctx = runtime
        try:
            resp = client.post(
                "/api/control",
                data=json.dumps({"action": "explode"}),
                content_type="application/json",
            )
            assert resp.status_code == 400
        finally:
            rt.ctx = None

    def test_api_control_pause_resume(self, client):
        runtime = WebRuntime()
        runtime.state = SimState()
        rt.ctx = runtime
        try:
            resp = client.post(
                "/api/control",
                data=json.dumps({"action": "pause"}),
                content_type="application/json",
            )
            assert resp.status_code == 200
            data = json.loads(resp.data)
            assert data["paused"] is True

            resp = client.post(
                "/api/control",
                data=json.dumps({"action": "resume"}),
                content_type="application/json",
            )
            data = json.loads(resp.data)
            assert data["paused"] is False
        finally:
            rt.ctx = None

    def test_api_control_toggle_vfd(self, client):
        runtime = WebRuntime()
        runtime.state = SimState()
        rt.ctx = runtime
        try:
            resp = client.post(
                "/api/control",
                data=json.dumps({"action": "toggle_vfd"}),
                content_type="application/json",
            )
            data = json.loads(resp.data)
            assert data["auto_speed"] is False  # 默认 True → toggle → False
        finally:
            rt.ctx = None

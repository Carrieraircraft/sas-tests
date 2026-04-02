"""批头选配器配置测试。"""

import pytest

pytestmark = [pytest.mark.peripheral, pytest.mark.p1, pytest.mark.hardware]


class TestSocketTray:
    async def test_socket_tray_query_reachable(self, ws):
        resp = await ws.request(
            {"type": "SocketTray_config_query"},
            "SocketTray_config_query_response",
        )
        assert resp.get("type") == "SocketTray_config_query_response"
        assert "success" in resp

    async def test_socket_tray_set_invalid_pset_count(self, ws):
        resp = await ws.request(
            {"type": "SocketTray_config_set", "enabled": True, "comm_mode": 0, "pset_count": 0},
            "SocketTray_config_set_response",
        )
        assert resp.get("type") == "SocketTray_config_set_response"
        assert resp.get("success") is False


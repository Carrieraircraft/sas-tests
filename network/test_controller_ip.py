"""控制器 IP 配置测试。"""

import pytest

pytestmark = [pytest.mark.network, pytest.mark.p1]


class TestControllerIP:
    async def test_controller_ip_query(self, ws):
        resp = await ws.request({"type": "controller_ip_query"}, "controller_ip_query_response")
        assert resp.get("type") == "controller_ip_query_response"
        assert "success" in resp

    async def test_controller_ip_set_invalid_payload(self, ws):
        resp = await ws.request({"type": "controller_ip_set"}, "controller_ip_set_response")
        assert resp.get("type") == "controller_ip_set_response"
        assert resp.get("success") is False


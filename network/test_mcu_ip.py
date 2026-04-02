"""MCU IP 配置测试。"""

import pytest

pytestmark = [pytest.mark.network, pytest.mark.p1]


class TestMCUIP:
    async def test_mcu_ip_query(self, ws):
        resp = await ws.request({"type": "mcu_ip_query"}, "mcu_ip_query_response")
        assert resp.get("type") == "mcu_ip_query_response"
        assert "success" in resp

    async def test_mcu_ip_set_invalid_payload(self, ws):
        resp = await ws.request({"type": "mcu_ip_set"}, "mcu_ip_set_response")
        assert resp.get("type") == "mcu_ip_set_response"
        assert resp.get("success") is False


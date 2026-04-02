"""MCU DHCP 配置测试。"""

import pytest

pytestmark = [pytest.mark.network, pytest.mark.p1]


class TestMCUDHCP:
    async def test_mcu_dhcp_query(self, ws):
        resp = await ws.request({"type": "mcu_dhcp_query"}, "mcu_dhcp_query_response")
        assert resp.get("type") == "mcu_dhcp_query_response"
        assert "success" in resp

    async def test_mcu_dhcp_set_invalid_payload(self, ws):
        resp = await ws.request({"type": "mcu_dhcp_set"}, "mcu_dhcp_set_response")
        assert resp.get("type") == "mcu_dhcp_set_response"
        assert resp.get("success") is False


"""Modbus 配置测试。"""

import pytest

pytestmark = [pytest.mark.network, pytest.mark.p1]


class TestModbus:
    async def test_modbus_query(self, ws):
        resp = await ws.request({"type": "modbus_config_query"}, "modbus_config_query_response")
        assert resp.get("type") == "modbus_config_query_response"
        assert "success" in resp

    async def test_modbus_set_invalid_payload(self, ws):
        resp = await ws.request({"type": "modbus_config_set"}, "modbus_config_set_response")
        assert resp.get("type") == "modbus_config_set_response"
        assert resp.get("success") is False


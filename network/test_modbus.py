"""Modbus 配置测试。"""

import pytest

pytestmark = [pytest.mark.network, pytest.mark.p1]


class TestModbus:
    async def test_modbus_query(self, ws):
        resp = await ws.request({"type": "modbus_config_query"}, "modbus_config_query_response")
        assert resp.get("type") == "modbus_config_query_response"
        assert "success" in resp
        if resp.get("success"):
            data = resp.get("data", {})
            # Modbus 参数已改由 MCU 配置区读写，查询只返回 tcpPort/slaveNo/addrShift（无 enableProtocol）
            assert "tcpPort" in data
            assert "slaveNo" in data
            assert "addrShift" in data

    async def test_modbus_set_invalid_payload(self, ws):
        resp = await ws.request({"type": "modbus_config_set"}, "modbus_config_set_response")
        assert resp.get("type") == "modbus_config_set_response"
        assert resp.get("success") is False

    async def test_modbus_set_roundtrip_disabled(self, ws_auth):
        """写回 Modbus 参数，验证写入 MCU 配置区后查询回读字段一致。

        使用默认参数（1502/1/0），对现场无副作用。需要登录态（ws_auth）。
        """
        set_resp = await ws_auth.request(
            {
                "type": "modbus_config_set",
                "enableProtocol": False,
                "tcpPort": 1502,
                "slaveNo": 1,
                "addrShift": 0,
            },
            "modbus_config_set_response",
        )
        assert set_resp.get("type") == "modbus_config_set_response"
        assert set_resp.get("success") is True

        query_resp = await ws_auth.request({"type": "modbus_config_query"}, "modbus_config_query_response")
        assert query_resp.get("success") is True
        data = query_resp.get("data", {})
        assert data.get("tcpPort") == 1502
        assert data.get("slaveNo") == 1
        assert data.get("addrShift") == 0

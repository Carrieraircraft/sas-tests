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
            # 字段名对齐 ModbusConfig 表: enableProtocol/tcpPort/slaveNo/addrShift
            assert "enableProtocol" in data
            assert "tcpPort" in data
            assert "slaveNo" in data
            assert "addrShift" in data

    async def test_modbus_set_invalid_payload(self, ws):
        resp = await ws.request({"type": "modbus_config_set"}, "modbus_config_set_response")
        assert resp.get("type") == "modbus_config_set_response"
        assert resp.get("success") is False

    async def test_modbus_set_roundtrip_disabled(self, ws_auth):
        """保持禁用态写回，验证 DataQueryService 落库 + 查询回读字段一致。

        不启用协议（enableProtocol=False），避免实际拉起 ModbusFacade 监听端口，
        对现场环境无副作用，可在冒烟测试中安全运行。需要登录态（ws_auth），
        否则后端一律回 {"success": false, "error": "未登录"}。
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
        assert data.get("enableProtocol") is False
        assert data.get("tcpPort") == 1502
        assert data.get("slaveNo") == 1
        assert data.get("addrShift") == 0

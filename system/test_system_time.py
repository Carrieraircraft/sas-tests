"""系统时间接口测试。"""

import pytest

pytestmark = [pytest.mark.system, pytest.mark.p1]


class TestSystemTime:
    async def test_system_time_get(self, ws):
        resp = await ws.request({"type": "system_time_get"}, "system_time_get_response")
        assert resp.get("type") == "system_time_get_response"
        assert "success" in resp

    async def test_system_time_set_invalid(self, ws):
        resp = await ws.request({"type": "system_time_set"}, "system_time_set_response")
        assert resp.get("type") == "system_time_set_response"
        assert resp.get("success") is False

    async def test_system_time_calibrate(self, ws):
        resp = await ws.request({"type": "system_time_calibrate"}, "system_time_calibrate_response")
        assert resp.get("type") == "system_time_calibrate_response"
        assert "success" in resp


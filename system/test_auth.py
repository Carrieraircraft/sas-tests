"""认证与密码接口测试。"""

import pytest

pytestmark = [pytest.mark.system, pytest.mark.p1]


class TestAuth:
    async def test_role_switch_invalid(self, ws):
        resp = await ws.request({"type": "role_switch"}, "role_switch_response")
        assert resp.get("type") == "role_switch_response"
        assert resp.get("success") is False

    async def test_update_password_invalid(self, ws):
        resp = await ws.request({"type": "update_password"}, "update_password_response")
        assert resp.get("type") == "update_password_response"
        assert resp.get("success") is False


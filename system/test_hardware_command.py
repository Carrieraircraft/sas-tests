"""硬件命令接口测试。"""

import pytest

pytestmark = [pytest.mark.system, pytest.mark.p1]


class TestHardwareCommand:
    async def test_hardware_command_invalid(self, ws):
        resp = await ws.request({"type": "hardware_command"}, "hardware_response")
        assert resp.get("type") == "hardware_response"
        assert resp.get("success") is False


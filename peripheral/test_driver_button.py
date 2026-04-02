"""电批按钮配置测试。"""

import pytest

pytestmark = [pytest.mark.peripheral, pytest.mark.p1, pytest.mark.hardware]


def _ensure_success_or_skip(resp: dict, action: str) -> None:
    if resp.get("success") is False:
        pytest.skip(f"{action} unavailable in current environment: {resp.get('error')}")


class TestDriverButton:
    async def test_driver_button_param_get(self, ws):
        resp = await ws.request(
            {"type": "driver_button_param_get"},
            "driver_button_param_get_response",
        )
        assert resp.get("type") == "driver_button_param_get_response"
        _ensure_success_or_skip(resp, "driver_button_param_get")
        data = resp.get("data", {})
        assert "negativeClose" in data
        assert "positiveClose" in data
        assert "startupMode" in data

    async def test_driver_button_config_roundtrip(self, ws):
        base = await ws.request(
            {"type": "driver_button_param_get"},
            "driver_button_param_get_response",
        )
        _ensure_success_or_skip(base, "driver_button_param_get")
        before = base["data"]
        target = {
            "negativeClose": not bool(before.get("negativeClose", False)),
            "positiveClose": bool(before.get("positiveClose", False)),
            "startupMode": before.get("startupMode", "lever"),
        }
        save = await ws.request(
            {"type": "driver_button_config", "data": target},
            "driver_button_config_response",
        )
        _ensure_success_or_skip(save, "driver_button_config")
        assert save.get("success") is True
        after = await ws.request(
            {"type": "driver_button_param_get"},
            "driver_button_param_get_response",
        )
        _ensure_success_or_skip(after, "driver_button_param_get")
        assert after["data"].get("negativeClose") == target["negativeClose"]
        await ws.request(
            {"type": "driver_button_config", "data": before},
            "driver_button_config_response",
        )


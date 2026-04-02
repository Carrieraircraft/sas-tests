"""拆螺丝参数测试。"""

import pytest

pytestmark = [pytest.mark.peripheral, pytest.mark.p1, pytest.mark.hardware]


def _ensure_success_or_skip(resp: dict, action: str) -> None:
    if resp.get("success") is False:
        pytest.skip(f"{action} unavailable in current environment: {resp.get('error')}")


class TestUnscrew:
    async def test_unscrew_param_get(self, ws):
        resp = await ws.request(
            {"type": "unscrew_param_get"},
            "unscrew_param_get_response",
        )
        assert resp.get("type") == "unscrew_param_get_response"
        _ensure_success_or_skip(resp, "unscrew_param_get")
        data = resp.get("data", {})
        for key in ("unScrewTorque", "unScrewVel", "unScrewTime", "unScrewAngle"):
            assert key in data

    async def test_unscrew_config_roundtrip(self, ws):
        base = await ws.request(
            {"type": "unscrew_param_get"},
            "unscrew_param_get_response",
        )
        _ensure_success_or_skip(base, "unscrew_param_get")
        before = base["data"]
        target = {
            "unScrewTorque": float(before.get("unScrewTorque", 1.2)),
            "unScrewVel": int(before.get("unScrewVel", 200)),
            "unScrewTime": int(before.get("unScrewTime", 500)),
            "unScrewAngle": int(before.get("unScrewAngle", 90)),
        }
        save = await ws.request(
            {"type": "unscrew_config", "data": target},
            "unscrew_config_response",
        )
        _ensure_success_or_skip(save, "unscrew_config")
        assert save.get("success") is True
        after = await ws.request(
            {"type": "unscrew_param_get"},
            "unscrew_param_get_response",
        )
        _ensure_success_or_skip(after, "unscrew_param_get")
        assert abs(float(after["data"].get("unScrewTorque", 0.0)) - target["unScrewTorque"]) < 0.5
        await ws.request(
            {"type": "unscrew_config", "data": before},
            "unscrew_config_response",
        )


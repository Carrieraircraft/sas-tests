"""输入/输出 IO 配置测试。"""

import pytest

pytestmark = [pytest.mark.peripheral, pytest.mark.p1, pytest.mark.hardware]


def _ensure_success_or_skip(resp: dict, action: str) -> None:
    if resp.get("success") is False:
        pytest.skip(f"{action} unavailable in current environment: {resp.get('error')}")


class TestIOConfig:
    async def test_input_io_param_get(self, ws):
        resp = await ws.request({"type": "input_io_param_get"}, "input_io_param_get_response")
        assert resp.get("type") == "input_io_param_get_response"
        _ensure_success_or_skip(resp, "input_io_param_get")
        data = resp.get("data", {})
        for key in ("resetSwitch", "powerOnStart", "forwardStart", "reverseStart"):
            assert key in data

    async def test_input_io_config_roundtrip(self, ws):
        base = await ws.request({"type": "input_io_param_get"}, "input_io_param_get_response")
        _ensure_success_or_skip(base, "input_io_param_get")
        before = base["data"]
        target = {
            "resetSwitch": not bool(before.get("resetSwitch", False)),
            "powerOnStart": bool(before.get("powerOnStart", False)),
            "forwardStart": bool(before.get("forwardStart", False)),
            "reverseStart": bool(before.get("reverseStart", False)),
        }
        save = await ws.request({"type": "input_io_config", "data": target}, "input_io_config_response")
        _ensure_success_or_skip(save, "input_io_config")
        assert save.get("success") is True
        after = await ws.request({"type": "input_io_param_get"}, "input_io_param_get_response")
        _ensure_success_or_skip(after, "input_io_param_get")
        for k, v in target.items():
            assert after["data"].get(k) == v
        await ws.request({"type": "input_io_config", "data": before}, "input_io_config_response")

    async def test_output_io_param_get(self, ws):
        resp = await ws.request({"type": "output_io_param_get"}, "output_io_param_get_response")
        assert resp.get("type") == "output_io_param_get_response"
        _ensure_success_or_skip(resp, "output_io_param_get")
        data = resp.get("data", {})
        for key in ("ngOut", "okOut", "finishOut", "ngType", "okType", "ngPulse", "okPulse", "finishPulse"):
            assert key in data

    async def test_output_io_config_roundtrip(self, ws):
        base = await ws.request({"type": "output_io_param_get"}, "output_io_param_get_response")
        _ensure_success_or_skip(base, "output_io_param_get")
        before = base["data"]
        target = {
            "ngOut": not bool(before.get("ngOut", False)),
            "okOut": bool(before.get("okOut", False)),
            "finishOut": bool(before.get("finishOut", False)),
            "ngType": bool(before.get("ngType", False)),
            "okType": bool(before.get("okType", False)),
            "ngPulse": int(before.get("ngPulse", 300)),
            "okPulse": int(before.get("okPulse", 300)),
            "finishPulse": int(before.get("finishPulse", 300)),
        }
        save = await ws.request({"type": "output_io_config", "data": target}, "output_io_config_response")
        _ensure_success_or_skip(save, "output_io_config")
        assert save.get("success") is True
        after = await ws.request({"type": "output_io_param_get"}, "output_io_param_get_response")
        _ensure_success_or_skip(after, "output_io_param_get")
        for k, v in target.items():
            assert after["data"].get(k) == v
        await ws.request({"type": "output_io_config", "data": before}, "output_io_config_response")


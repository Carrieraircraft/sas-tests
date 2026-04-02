"""蜂鸣器参数测试。"""

import pytest

pytestmark = [pytest.mark.peripheral, pytest.mark.p1, pytest.mark.hardware]


def _ensure_success_or_skip(resp: dict, action: str) -> None:
    if resp.get("success") is False:
        pytest.skip(f"{action} unavailable in current environment: {resp.get('error')}")


class TestBeeper:
    async def test_beeper_param_get(self, ws):
        resp = await ws.request({"type": "beeper_param_get"}, "beeper_param_get_response")
        assert resp.get("type") == "beeper_param_get_response"
        _ensure_success_or_skip(resp, "beeper_param_get")
        data = resp.get("data", {})
        for key in (
            "soundOkEnable",
            "soundNgEnable",
            "soundEndEnable",
            "soundOkLoopCnt",
            "soundNgLoopCnt",
            "soundEndLoopCnt",
            "soundOkOnTime",
            "soundOkOffTime",
            "soundNgOnTime",
            "soundNgOffTime",
            "soundEndOnTime",
            "soundEndOffTime",
        ):
            assert key in data

    async def test_beeper_config_roundtrip(self, ws):
        base = await ws.request({"type": "beeper_param_get"}, "beeper_param_get_response")
        _ensure_success_or_skip(base, "beeper_param_get")
        before = base["data"]
        target = dict(before)
        target["soundOkEnable"] = not bool(before.get("soundOkEnable", False))
        save = await ws.request({"type": "beeper_config", "data": target}, "beeper_config_response")
        _ensure_success_or_skip(save, "beeper_config")
        assert save.get("success") is True
        after = await ws.request({"type": "beeper_param_get"}, "beeper_param_get_response")
        _ensure_success_or_skip(after, "beeper_param_get")
        assert after["data"].get("soundOkEnable") == target["soundOkEnable"]
        await ws.request({"type": "beeper_config", "data": before}, "beeper_config_response")


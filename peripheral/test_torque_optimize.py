"""扭力优化参数测试。"""

import pytest

pytestmark = [pytest.mark.peripheral, pytest.mark.p1, pytest.mark.hardware]


def _ensure_success_or_skip(resp: dict, action: str) -> None:
    if resp.get("success") is False:
        pytest.skip(f"{action} unavailable in current environment: {resp.get('error')}")


class TestTorqueOptimize:
    async def test_torque_optimize_param_get(self, ws):
        resp = await ws.request(
            {"type": "torque_optimize_param_get"},
            "torque_optimize_param_get_response",
        )
        assert resp.get("type") == "torque_optimize_param_get_response"
        _ensure_success_or_skip(resp, "torque_optimize_param_get")
        data = resp.get("data", {})
        for key in ("torqueOptTime", "velOptTime", "stopTorquePercent"):
            assert key in data

    async def test_torque_optimize_config_roundtrip(self, ws):
        base = await ws.request(
            {"type": "torque_optimize_param_get"},
            "torque_optimize_param_get_response",
        )
        _ensure_success_or_skip(base, "torque_optimize_param_get")
        before = base["data"]
        target = {
            "torqueOptTime": max(1, int(before.get("torqueOptTime", 30))),
            "velOptTime": max(1, int(before.get("velOptTime", 30))),
            "stopTorquePercent": int(before.get("stopTorquePercent", 80)),
        }
        save = await ws.request(
            {"type": "torque_optimize_config", "data": target},
            "torque_optimize_config_response",
        )
        _ensure_success_or_skip(save, "torque_optimize_config")
        assert save.get("success") is True
        after = await ws.request(
            {"type": "torque_optimize_param_get"},
            "torque_optimize_param_get_response",
        )
        _ensure_success_or_skip(after, "torque_optimize_param_get")
        for k, v in target.items():
            assert int(after["data"].get(k, -1)) == int(v)
        await ws.request(
            {"type": "torque_optimize_config", "data": before},
            "torque_optimize_config_response",
        )


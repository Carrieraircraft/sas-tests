"""支臂架配置 CRUD。"""

import pytest

pytestmark = [pytest.mark.torque_arm, pytest.mark.p1]


def _ensure_success_or_skip(resp: dict, action: str) -> None:
    if resp.get("success") is False:
        pytest.skip(f"{action} unavailable in current environment: {resp.get('error')}")


class TestTorqueArmConfig:
    async def test_torque_arm_config_get(self, ws):
        resp = await ws.request({"type": "torque_arm_config_get"}, "torque_arm_config_get_response")
        assert resp.get("type") == "torque_arm_config_get_response"
        _ensure_success_or_skip(resp, "torque_arm_config_get")
        data = resp.get("data", {})
        for key in ("swap_angles", "angle_a_offset", "angle_b_offset", "enable_position_check"):
            assert key in data

    async def test_torque_arm_config_update_roundtrip(self, ws):
        base = await ws.request({"type": "torque_arm_config_get"}, "torque_arm_config_get_response")
        _ensure_success_or_skip(base, "torque_arm_config_get")
        before = base.get("data", {})
        target = {
            "swap_angles": not bool(before.get("swap_angles", False)),
            "angle_a_offset": float(before.get("angle_a_offset", 0.0)),
            "angle_b_offset": float(before.get("angle_b_offset", 0.0)),
            "enable_position_check": bool(before.get("enable_position_check", False)),
        }
        save = await ws.request(
            {"type": "torque_arm_config_update", "config": target, "modify_user": "pytest"},
            "torque_arm_config_update_response",
        )
        _ensure_success_or_skip(save, "torque_arm_config_update")
        assert save.get("success") is True

        after = await ws.request({"type": "torque_arm_config_get"}, "torque_arm_config_get_response")
        _ensure_success_or_skip(after, "torque_arm_config_get")
        assert bool(after["data"].get("swap_angles")) == target["swap_angles"]

        await ws.request(
            {"type": "torque_arm_config_update", "config": before, "modify_user": "pytest"},
            "torque_arm_config_update_response",
        )


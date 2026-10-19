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
        # 后端一律回传新格式（旧的 swap_angles/angle_x_offset 只在读库时做迁移）
        for key in ("encoder_count", "encoder_mapping", "angle_offsets", "axis_types",
                    "enable_position_check"):
            assert key in data

    async def test_torque_arm_config_update_roundtrip(self, ws):
        base = await ws.request({"type": "torque_arm_config_get"}, "torque_arm_config_get_response")
        _ensure_success_or_skip(base, "torque_arm_config_get")
        before = base.get("data", {})
        offsets = list(before.get("angle_offsets", [0.0, 0.0, 0.0, 0.0]))
        target = dict(before)
        target["angle_offsets"] = [offsets[0] + 1.5] + offsets[1:]
        save = await ws.request(
            {"type": "torque_arm_config_update", "config": target, "modify_user": "pytest"},
            "torque_arm_config_update_response",
        )
        _ensure_success_or_skip(save, "torque_arm_config_update")
        assert save.get("success") is True

        after = await ws.request({"type": "torque_arm_config_get"}, "torque_arm_config_get_response")
        _ensure_success_or_skip(after, "torque_arm_config_get")
        assert after["data"]["angle_offsets"][0] == pytest.approx(target["angle_offsets"][0])

        await ws.request(
            {"type": "torque_arm_config_update", "config": before, "modify_user": "pytest"},
            "torque_arm_config_update_response",
        )

    async def test_legacy_swap_migrates_offsets_with_channel(self, ws):
        """旧格式 swap_angles=true 时零点偏移必须随物理通道换位。

        旧实现的偏移绑定物理通道（raw_a-offset_a / raw_b-offset_b，之后再交换），
        新格式绑定逻辑轴，漏掉换位会让升级后两轴零点互相错位。
        """
        base = await ws.request({"type": "torque_arm_config_get"}, "torque_arm_config_get_response")
        _ensure_success_or_skip(base, "torque_arm_config_get")
        before = base.get("data", {})

        legacy = {"swap_angles": True, "angle_a_offset": 11.0, "angle_b_offset": 22.0,
                  "enable_position_check": False}
        save = await ws.request(
            {"type": "torque_arm_config_update", "config": legacy, "modify_user": "pytest"},
            "torque_arm_config_update_response",
        )
        _ensure_success_or_skip(save, "torque_arm_config_update")

        migrated = save["data"]
        assert migrated["encoder_mapping"][:2] == [1, 0]
        # 逻辑轴1 绑到通道B，就该带走通道B 的零点
        assert migrated["angle_offsets"][0] == pytest.approx(22.0)
        assert migrated["angle_offsets"][1] == pytest.approx(11.0)

        await ws.request(
            {"type": "torque_arm_config_update", "config": before, "modify_user": "pytest"},
            "torque_arm_config_update_response",
        )


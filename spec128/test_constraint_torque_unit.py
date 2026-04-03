"""机种约束 + 扭矩单位转换 + 安全开关清零 回归测试。

覆盖目标（对应三轮修复的 bug）：
1) 安全开关全关 + 机种约束 → 清零后的安全参数不应触发约束校验
2) 步骤 ref_torque 以 N·m 存储，约束以 kgf.cm 定义 → 后端应自动转换后比较
3) seat_point_torque_factor = 0 不应被 validateParamRelations 拦截
4) 保存被后端拒绝时返回 success: false（前端假成功场景模拟）
5) 扭力值保存回读一致（不被"篡改"）
"""

from __future__ import annotations

import pytest

from lib.helpers import ScrewSpecFactory

pytestmark = [pytest.mark.spec128, pytest.mark.p0]

_SID = 99

UNIT_KGFCM_TO_NM = 0.0980665


async def _activate(ws, spec_id: int) -> None:
    await ws.request(
        {"type": "screw_spec_set_active", "spec_id": spec_id, "is_active": True},
        "screw_spec_set_active_response",
    )


async def _deactivate(ws, spec_id: int) -> None:
    await ws.request(
        {"type": "screw_spec_set_active", "spec_id": spec_id, "is_active": False},
        "screw_spec_set_active_response",
    )


async def _get_first_machine_type_with_constraints(ws) -> int | None:
    """查询后端已有的机种列表，返回第一个有约束的机种 ID。"""
    resp = await ws.request(
        {"type": "machine_type_list_query"},
        "machine_type_list_response",
    )
    machine_types = resp.get("data") or resp.get("machineTypes") or []
    for mt in machine_types:
        mt_id = mt.get("id") or mt.get("machine_type_id")
        if mt_id and mt_id > 0:
            return mt_id
    return None


async def _get_torque_constraint(ws, machine_type_id: int, unit: str = "kgf.cm"):
    """查询指定机种的 torque 约束范围。"""
    resp = await ws.request(
        {"type": "machine_type_constraints_query", "machineTypeId": machine_type_id},
        "machine_type_constraints_response",
    )
    constraints = resp.get("constraints") or []
    for c in constraints:
        if c.get("paramName") == "torque" and c.get("torqueUnit") == unit:
            return c.get("minValue"), c.get("maxValue")
    return None, None


async def _get_vel_constraint(ws, machine_type_id: int):
    """查询指定机种的 ref_vel 约束范围。"""
    resp = await ws.request(
        {"type": "machine_type_constraints_query", "machineTypeId": machine_type_id},
        "machine_type_constraints_response",
    )
    constraints = resp.get("constraints") or []
    for c in constraints:
        if c.get("paramName") == "ref_vel":
            return c.get("minValue"), c.get("maxValue")
    return None, None


async def _get_constraint(ws, machine_type_id: int, param_name: str, unit: str = ""):
    """查询指定机种的任意参数约束范围。"""
    resp = await ws.request(
        {"type": "machine_type_constraints_query", "machineTypeId": machine_type_id},
        "machine_type_constraints_response",
    )
    constraints = resp.get("constraints") or []
    for c in constraints:
        matches_name = c.get("paramName") == param_name
        matches_unit = (not unit and not c.get("torqueUnit")) or c.get("torqueUnit") == unit
        if matches_name and matches_unit:
            return c.get("minValue"), c.get("maxValue")
    return None, None


def _safe_mid_nm(constraint_min, constraint_max):
    """给定 kgf.cm 约束范围，返回范围中点的 N·m 值。"""
    mid_kgfcm = (constraint_min + constraint_max) / 2
    return mid_kgfcm * UNIT_KGFCM_TO_NM


class TestSafetyDisabledWithConstraint:
    """安全开关全关 + 有机种约束时，保存应成功（清零的安全参数不参与约束校验）。"""

    async def test_all_safety_off_with_machine_type_saves_ok(self, ws):
        mt_id = await _get_first_machine_type_with_constraints(ws)
        if mt_id is None:
            pytest.skip("没有可用的机种约束数据")

        torque_min, torque_max = await _get_torque_constraint(ws, mt_id)
        if torque_min is None:
            pytest.skip("该机种没有 torque 约束")

        vel_min, vel_max = await _get_vel_constraint(ws, mt_id)
        clamp_min_lo, clamp_min_hi = await _get_constraint(ws, mt_id, "clamp_torque_min", "kgf.cm")
        clamp_max_lo, clamp_max_hi = await _get_constraint(ws, mt_id, "clamp_torque_max", "kgf.cm")

        sid = _SID
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.default(sid)
            payload["machine_type_id"] = mt_id
            d = payload["detail_params"]

            d["torque_check_enable"] = 0
            d["time_check_enable"] = 0
            d["vel_check_enable"] = 0
            d["degree_check_enable"] = 0
            d["torque_target"] = 0
            d["torque_min"] = 0
            d["torque_max"] = 0
            d["vel_target"] = 0
            d["vel_min"] = 0
            d["vel_max"] = 0
            d["time_target"] = 0
            d["time_min"] = 0
            d["time_max"] = 0
            d["degree_target"] = 0
            d["degree_min"] = 0
            d["degree_max"] = 0

            d["seat_point_torque_factor"] = 0

            # 夹紧扭力使用约束范围中点（kgf.cm → N·m）
            if clamp_min_hi is not None:
                d["clamp_torque_min"] = _safe_mid_nm(clamp_min_lo, clamp_min_hi)
            else:
                d["clamp_torque_min"] = 0
            if clamp_max_hi is not None:
                d["clamp_torque_max"] = _safe_mid_nm(clamp_max_lo, clamp_max_hi)
            else:
                d["clamp_torque_max"] = 0

            ref_torque_nm = _safe_mid_nm(torque_min, torque_max)

            safe_vel = 180
            if vel_min is not None and vel_max is not None:
                safe_vel = int((vel_min + vel_max) / 2)

            payload["step_params"][0]["ref_torque"] = round(ref_torque_nm, 6)
            payload["step_params"][0]["ref_vel"] = safe_vel

            resp = await ws.save_screw_param(sid, payload)
            assert resp.get("success") is True, (
                f"安全开关全关 + 机种约束，保存应成功，实际: {resp}"
            )
        finally:
            await _deactivate(ws, sid)


class TestTorqueUnitConversion:
    """步骤 ref_torque (N·m) 应在与约束比较前转换为用户单位。"""

    async def test_step_torque_within_constraint_saves_ok(self, ws):
        """步骤扭力在约束范围内（kgf.cm），保存应成功。"""
        mt_id = await _get_first_machine_type_with_constraints(ws)
        if mt_id is None:
            pytest.skip("没有可用的机种约束数据")

        torque_min, torque_max = await _get_torque_constraint(ws, mt_id)
        if torque_min is None:
            pytest.skip("该机种没有 torque 约束")

        vel_min, vel_max = await _get_vel_constraint(ws, mt_id)
        clamp_min_lo, clamp_min_hi = await _get_constraint(ws, mt_id, "clamp_torque_min", "kgf.cm")
        clamp_max_lo, clamp_max_hi = await _get_constraint(ws, mt_id, "clamp_torque_max", "kgf.cm")

        sid = _SID
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.default(sid)
            payload["machine_type_id"] = mt_id
            d = payload["detail_params"]

            d["torque_check_enable"] = 1
            d["torque_min"] = torque_min * UNIT_KGFCM_TO_NM
            d["torque_max"] = torque_max * UNIT_KGFCM_TO_NM
            d["torque_target"] = _safe_mid_nm(torque_min, torque_max)

            d["time_check_enable"] = 0
            d["vel_check_enable"] = 0
            d["degree_check_enable"] = 0

            if clamp_min_hi is not None:
                d["clamp_torque_min"] = _safe_mid_nm(clamp_min_lo, clamp_min_hi)
            else:
                d["clamp_torque_min"] = 0
            if clamp_max_hi is not None:
                d["clamp_torque_max"] = _safe_mid_nm(clamp_max_lo, clamp_max_hi)
            else:
                d["clamp_torque_max"] = 0

            ref_torque_nm = _safe_mid_nm(torque_min, torque_max)

            safe_vel = 180
            if vel_min is not None and vel_max is not None:
                safe_vel = int((vel_min + vel_max) / 2)

            payload["step_params"][0]["ref_torque"] = round(ref_torque_nm, 6)
            payload["step_params"][0]["ref_vel"] = safe_vel

            resp = await ws.save_screw_param(sid, payload)
            assert resp.get("success") is True, (
                f"步骤扭力在约束 [{torque_min}, {torque_max}] 内，保存应成功，实际: {resp}"
            )
        finally:
            await _deactivate(ws, sid)

    async def test_step_torque_exceeds_constraint_rejected(self, ws):
        """步骤扭力超出约束上界（kgf.cm），保存应被拒绝。"""
        mt_id = await _get_first_machine_type_with_constraints(ws)
        if mt_id is None:
            pytest.skip("没有可用的机种约束数据")

        torque_min, torque_max = await _get_torque_constraint(ws, mt_id)
        if torque_min is None:
            pytest.skip("该机种没有 torque 约束")

        vel_min, vel_max = await _get_vel_constraint(ws, mt_id)
        clamp_min_lo, clamp_min_hi = await _get_constraint(ws, mt_id, "clamp_torque_min", "kgf.cm")
        clamp_max_lo, clamp_max_hi = await _get_constraint(ws, mt_id, "clamp_torque_max", "kgf.cm")

        sid = _SID
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.default(sid)
            payload["machine_type_id"] = mt_id
            d = payload["detail_params"]
            d["torque_check_enable"] = 0
            d["time_check_enable"] = 0
            d["vel_check_enable"] = 0
            d["degree_check_enable"] = 0

            if clamp_min_hi is not None:
                d["clamp_torque_min"] = _safe_mid_nm(clamp_min_lo, clamp_min_hi)
            else:
                d["clamp_torque_min"] = 0
            if clamp_max_hi is not None:
                d["clamp_torque_max"] = _safe_mid_nm(clamp_max_lo, clamp_max_hi)
            else:
                d["clamp_torque_max"] = 0

            over_nm = (torque_max + 1) * UNIT_KGFCM_TO_NM

            safe_vel = 180
            if vel_min is not None and vel_max is not None:
                safe_vel = int((vel_min + vel_max) / 2)

            payload["step_params"][0]["ref_torque"] = round(over_nm, 6)
            payload["step_params"][0]["ref_vel"] = safe_vel

            resp = await ws.save_screw_param(sid, payload)
            assert resp.get("success") is False, (
                f"步骤扭力 {torque_max + 1} kgf.cm 超过约束上界 {torque_max}，保存应被拒绝，实际: {resp}"
            )
            err = str(resp.get("error", ""))
            assert "步骤" in err or "torque" in err or "扭力" in err, (
                f"错误信息应提及步骤/扭力，实际: {resp.get('error')}"
            )
        finally:
            await _deactivate(ws, sid)


class TestSeatPointTorqueFactorZero:
    """seat_point_torque_factor = 0（不使用夹紧检测）不应被参数关系校验拦截。"""

    async def test_factor_zero_saves_ok(self, ws):
        sid = _SID
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.default(sid)
            payload["machine_type_id"] = 0
            d = payload["detail_params"]
            d["seat_point_torque_factor"] = 0

            resp = await ws.save_screw_param(sid, payload)
            assert resp.get("success") is True, (
                f"seat_point_torque_factor=0 应合法保存，实际: {resp}"
            )
        finally:
            await _deactivate(ws, sid)

    async def test_factor_below_min_rejected(self, ws):
        """seat_point_torque_factor = 0.05（大于 0 但小于下限 0.1）应被拒绝。"""
        sid = _SID
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.default(sid)
            payload["machine_type_id"] = 0
            d = payload["detail_params"]
            d["seat_point_torque_factor"] = 0.05

            resp = await ws.save_screw_param(sid, payload)
            assert resp.get("success") is False, (
                f"seat_point_torque_factor=0.05 应被拒绝，实际: {resp}"
            )
        finally:
            await _deactivate(ws, sid)


class TestTorqueRoundtrip:
    """保存扭力值后回读，值不应被篡改。"""

    async def test_torque_values_survive_roundtrip(self, ws):
        mt_id = await _get_first_machine_type_with_constraints(ws)
        if mt_id is None:
            pytest.skip("没有可用的机种约束数据")

        torque_min, torque_max = await _get_torque_constraint(ws, mt_id)
        if torque_min is None:
            pytest.skip("该机种没有 torque 约束")

        vel_min, vel_max = await _get_vel_constraint(ws, mt_id)
        clamp_min_lo, clamp_min_hi = await _get_constraint(ws, mt_id, "clamp_torque_min", "kgf.cm")
        clamp_max_lo, clamp_max_hi = await _get_constraint(ws, mt_id, "clamp_torque_max", "kgf.cm")

        sid = _SID
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.with_steps(sid, 2)
            payload["machine_type_id"] = mt_id
            d = payload["detail_params"]
            d["torque_check_enable"] = 0
            d["time_check_enable"] = 0
            d["vel_check_enable"] = 0
            d["degree_check_enable"] = 0
            d["torque_unit"] = 1

            # 夹紧扭力用约束范围中点
            if clamp_min_hi is not None:
                d["clamp_torque_min"] = _safe_mid_nm(clamp_min_lo, clamp_min_hi)
            else:
                d["clamp_torque_min"] = 0
            if clamp_max_hi is not None:
                d["clamp_torque_max"] = _safe_mid_nm(clamp_max_lo, clamp_max_hi)
            else:
                d["clamp_torque_max"] = 0

            # 步骤扭力取约束范围的 30% 和 50% 位置
            step1_kgfcm = torque_min + (torque_max - torque_min) * 0.3
            step2_kgfcm = torque_min + (torque_max - torque_min) * 0.5
            step1_nm = step1_kgfcm * UNIT_KGFCM_TO_NM
            step2_nm = step2_kgfcm * UNIT_KGFCM_TO_NM

            safe_vel = 180
            if vel_min is not None and vel_max is not None:
                safe_vel = int((vel_min + vel_max) / 2)

            payload["step_params"][0]["ref_torque"] = round(step1_nm, 6)
            payload["step_params"][0]["ref_vel"] = safe_vel
            payload["step_params"][1]["ref_torque"] = round(step2_nm, 6)
            payload["step_params"][1]["ref_vel"] = safe_vel

            save_resp = await ws.save_screw_param(sid, payload)
            assert save_resp.get("success") is True, f"保存失败: {save_resp}"

            step_resp = await ws.request(
                {"type": "screw_step_param_get", "specification_id": sid},
                "screw_step_param_get_response",
            )
            assert step_resp.get("success") is True, f"步骤回读失败: {step_resp}"
            steps = step_resp.get("data", [])
            assert len(steps) >= 2, f"期望 2 个步骤，实际 {len(steps)}"

            read_torque_1 = float(steps[0].get("ref_torque", 0))
            read_torque_2 = float(steps[1].get("ref_torque", 0))
            assert abs(read_torque_1 - step1_nm) / max(step1_nm, 1e-9) < 0.001, (
                f"步骤1扭力回读不一致: 写入 {step1_nm:.6f}, 读回 {read_torque_1:.6f}"
            )
            assert abs(read_torque_2 - step2_nm) / max(step2_nm, 1e-9) < 0.001, (
                f"步骤2扭力回读不一致: 写入 {step2_nm:.6f}, 读回 {read_torque_2:.6f}"
            )
        finally:
            await _deactivate(ws, sid)


class TestSaveFailureReturnsError:
    """后端拒绝保存时应返回 success:false + error 消息（非假成功）。"""

    async def test_rejected_save_returns_false(self, ws):
        """发一个肯定会失败的保存（prog_start_valid_step >= prog_cnt），
        确认返回 success: false 而非 true。
        """
        sid = _SID
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.default(sid)
            payload["machine_type_id"] = 0
            d = payload["detail_params"]
            d["prog_cnt"] = 1
            d["prog_start_valid_step"] = 2

            resp = await ws.save_screw_param(sid, payload)
            assert resp.get("success") is False, (
                f"非法参数保存应返回 success:false，实际: {resp}"
            )
            assert resp.get("error"), (
                f"拒绝响应应包含 error 字段，实际: {resp}"
            )
        finally:
            await _deactivate(ws, sid)

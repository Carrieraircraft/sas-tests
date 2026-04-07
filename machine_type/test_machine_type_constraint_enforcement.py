"""机种约束后端执行回归测试（screw_param_config）。"""

from __future__ import annotations

import pytest

from lib.constants import MsgType
from lib.helpers import ScrewSpecFactory

pytestmark = [pytest.mark.machine_type, pytest.mark.p0]

# #region agent log
import json as _json, os as _os, time as _time
_LOG_PATH = _os.path.join(_os.path.dirname(__file__), "..", "..", "debug-5e949c.log")
def _dlog(hyp, loc, msg, data=None):
    entry = {"sessionId":"5e949c","hypothesisId":hyp,"location":loc,"message":msg,"data":data or {},"timestamp":int(_time.time()*1000)}
    with open(_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(_json.dumps(entry, ensure_ascii=False) + "\n")
# #endregion


def _as_float(value, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _outside_max(max_value: float) -> float:
    span = max(1.0, abs(max_value) * 0.2)
    return max_value + span


def _outside_min(min_value: float) -> float:
    span = max(1.0, abs(min_value) * 0.2)
    return min_value - span


def _extract_system_param_value(system_params_resp: dict, param_name: str) -> str | None:
    payload = system_params_resp.get("data", system_params_resp)
    if isinstance(payload, list):
        for item in payload:
            if item.get("param_name") == param_name or item.get("paramName") == param_name:
                return item.get("param_value") or item.get("paramValue")
    if isinstance(payload, dict):
        return payload.get(param_name)
    return None


def _extract_step_brief(step: dict) -> tuple[float, float, float, float]:
    return (
        _as_float(step.get("ref_vel")),
        _as_float(step.get("ref_torque")),
        _as_float(step.get("ref_degree")),
        _as_float(step.get("ref_time")),
    )


def _extract_detail_brief(detail: dict) -> tuple[float, float, float]:
    return (
        _as_float(detail.get("time_target")),
        _as_float(detail.get("torque_target")),
        _as_float(detail.get("vel_target")),
    )


def _extract_steps_brief_list(steps: list[dict]) -> list[tuple[float, float, float, float]]:
    return [_extract_step_brief(s) for s in steps]


def _torque_unit_str_to_code(unit: str | None) -> int | None:
    mapping = {
        "mN.m": 0,
        "kgf.cm": 1,
        "lbf.in": 2,
        "N.m": 3,
    }
    if not unit:
        return None
    return mapping.get(str(unit))


async def _set_system_param(ws, param_name: str, value: str) -> dict:
    msg = {
        "type": MsgType.SYSTEM_PARAM_UPDATE,
        "param_name": param_name,
        "param_value": str(value),
        "modify_user": "test",
    }
    return await ws.request(msg, MsgType.SYSTEM_PARAM_UPDATE_RESPONSE)


async def _find_machine_type_constraint(
    ws,
    param_name: str,
    require_empty_torque_unit: bool = False,
) -> tuple[int, dict] | tuple[None, None]:
    listing = await ws.request(
        {"type": "machine_type_list_query"},
        "machine_type_list_response",
    )
    rows = listing.get("data", [])
    for row in rows:
        machine_type_id = row.get("id")
        if not machine_type_id:
            continue
        resp = await ws.request(
            {"type": "machine_type_constraints_query", "machineTypeId": machine_type_id},
            "machine_type_constraints_response",
        )
        if not resp.get("success"):
            continue
        constraints = resp.get("constraints", [])
        for c in constraints:
            if c.get("paramName") != param_name:
                continue
            torque_unit = c.get("torqueUnit")
            is_empty = torque_unit in (None, "")
            if require_empty_torque_unit and not is_empty:
                continue
            return machine_type_id, c
    return None, None


async def _find_machine_type_constraints(
    ws,
    param_name: str,
    require_empty_torque_unit: bool = False,
) -> list[tuple[int, dict]]:
    matches: list[tuple[int, dict]] = []
    listing = await ws.request(
        {"type": "machine_type_list_query"},
        "machine_type_list_response",
    )
    rows = listing.get("data", [])
    for row in rows:
        machine_type_id = row.get("id")
        if not machine_type_id:
            continue
        resp = await ws.request(
            {"type": "machine_type_constraints_query", "machineTypeId": machine_type_id},
            "machine_type_constraints_response",
        )
        if not resp.get("success"):
            continue
        constraints = resp.get("constraints", [])
        for c in constraints:
            if c.get("paramName") != param_name:
                continue
            torque_unit = c.get("torqueUnit")
            is_empty = torque_unit in (None, "")
            if require_empty_torque_unit and not is_empty:
                continue
            matches.append((machine_type_id, c))
    return matches


def _pick_constraint_with_valid_range(matches: list[tuple[int, dict]]) -> tuple[int, dict] | tuple[None, None]:
    for machine_type_id, c in matches:
        min_v = _as_float(c.get("minValue"))
        max_v = _as_float(c.get("maxValue"))
        if max_v >= min_v:
            return machine_type_id, c
    return None, None


def _pick_torque_constraint_with_mappable_unit(
    matches: list[tuple[int, dict]],
) -> tuple[int, dict, int] | tuple[None, None, None]:
    for machine_type_id, c in matches:
        min_v = _as_float(c.get("minValue"))
        max_v = _as_float(c.get("maxValue"))
        if max_v < min_v:
            continue
        code = _torque_unit_str_to_code(c.get("torqueUnit"))
        if code is None:
            continue
        return machine_type_id, c, code
    return None, None, None


async def _widen_safety_for_constraints(ws, payload: dict, machine_type_id: int) -> None:
    """Adjust detail_params safety windows so they don't block before constraint check.

    Fetches all constraints for the machine type and widens vel/time/degree/torque
    min/max/target in detail_params to encompass the constraint range, ensuring
    validateParamRelations won't reject values that are within the constraint range.
    Also adjusts step_params defaults to sit within the widened safety window.
    """
    resp = await ws.request(
        {"type": "machine_type_constraints_query", "machineTypeId": machine_type_id},
        "machine_type_constraints_response",
    )
    constraints = {c["paramName"]: c for c in resp.get("constraints", [])}
    d = payload["detail_params"]

    def _widen(param_name: str, key_min: str, key_max: str, key_target: str,
               enable_key: str | None = None):
        c = constraints.get(param_name)
        if not c:
            return
        c_min = _as_float(c.get("minValue"))
        c_max = _as_float(c.get("maxValue"))
        cur_min = _as_float(d.get(key_min))
        cur_max = _as_float(d.get(key_max))
        new_min = min(cur_min, c_min)
        new_max = max(cur_max, c_max)
        d[key_min] = new_min
        d[key_max] = new_max
        cur_target = _as_float(d.get(key_target))
        if cur_target < new_min:
            d[key_target] = new_min
        if cur_target > new_max:
            d[key_target] = new_max

    _widen("ref_vel", "vel_min", "vel_max", "vel_target", "vel_check_enable")
    _widen("time_target", "time_min", "time_max", "time_target")
    _widen("time", "time_min", "time_max", "time_target")
    _widen("ref_degree", "degree_min", "degree_max", "degree_target")

    torque_constraints = [c for c in resp.get("constraints", []) if c.get("paramName") == "torque"]
    tc = None
    for tc_candidate in torque_constraints:
        code = _torque_unit_str_to_code(tc_candidate.get("torqueUnit"))
        if code is not None:
            tc = tc_candidate
            break
    if tc:
        t_min = _as_float(tc.get("minValue"))
        t_max = _as_float(tc.get("maxValue"))
        unit_code = _torque_unit_str_to_code(tc.get("torqueUnit"))
        if unit_code is not None:
            d["torque_unit"] = unit_code
        t_mid = (t_min + t_max) / 2
        d["torque_target"] = t_mid
        d["torque_min"] = t_min
        d["torque_max"] = t_max
        for step in payload.get("step_params", []):
            step["ref_torque"] = t_mid

    torque_unit_str = tc.get("torqueUnit") if tc else None
    cmin_candidates = [c for c in resp.get("constraints", [])
                       if c.get("paramName") == "clamp_torque_min"
                       and (not torque_unit_str or c.get("torqueUnit") == torque_unit_str)]
    cmax_candidates = [c for c in resp.get("constraints", [])
                       if c.get("paramName") == "clamp_torque_max"
                       and (not torque_unit_str or c.get("torqueUnit") == torque_unit_str)]
    cmin_c = cmin_candidates[0] if cmin_candidates else constraints.get("clamp_torque_min")
    cmax_c = cmax_candidates[0] if cmax_candidates else constraints.get("clamp_torque_max")
    if cmin_c:
        d["clamp_torque_min"] = _as_float(cmin_c.get("minValue"))
    if cmax_c:
        d["clamp_torque_max"] = _as_float(cmax_c.get("maxValue"))

    vel_c = constraints.get("ref_vel")
    if vel_c:
        v_mid = (_as_float(vel_c.get("minValue")) + _as_float(vel_c.get("maxValue"))) / 2
        for step in payload.get("step_params", []):
            step.setdefault("ref_vel", v_mid)
            if step["ref_vel"] < _as_float(d.get("vel_min")):
                step["ref_vel"] = _as_float(d.get("vel_min"))
            if step["ref_vel"] > _as_float(d.get("vel_max")):
                step["ref_vel"] = v_mid

    time_c = constraints.get("time") or constraints.get("time_target")
    if time_c:
        t_mid = (_as_float(time_c.get("minValue")) + _as_float(time_c.get("maxValue"))) / 2
        for step in payload.get("step_params", []):
            step.setdefault("ref_time", t_mid)
            if step["ref_time"] < _as_float(d.get("time_min")):
                step["ref_time"] = t_mid
            if step["ref_time"] > _as_float(d.get("time_max")):
                step["ref_time"] = t_mid

    deg_c = constraints.get("ref_degree")
    if deg_c:
        dg_mid = (_as_float(deg_c.get("minValue")) + _as_float(deg_c.get("maxValue"))) / 2
        for step in payload.get("step_params", []):
            step.setdefault("ref_degree", dg_mid)
            if step["ref_degree"] < _as_float(d.get("degree_min")):
                step["ref_degree"] = dg_mid
            if step["ref_degree"] > _as_float(d.get("degree_max")):
                step["ref_degree"] = dg_mid


def _pick_two_machine_types_with_different_max(
    matches: list[tuple[int, dict]],
) -> tuple[tuple[int, dict], tuple[int, dict]] | None:
    normalized: list[tuple[int, dict, float]] = []
    for machine_type_id, c in matches:
        min_v = _as_float(c.get("minValue"))
        max_v = _as_float(c.get("maxValue"))
        if max_v >= min_v:
            normalized.append((machine_type_id, c, max_v))

    if len(normalized) < 2:
        return None

    normalized.sort(key=lambda x: x[2])
    strict = normalized[0]
    loose = normalized[-1]
    if loose[2] <= strict[2]:
        return None
    return (strict[0], strict[1]), (loose[0], loose[1])


@pytest.fixture
async def restore_current_machine_type(ws):
    original_params = await ws.get_system_params()
    original_value = _extract_system_param_value(original_params, "CurrentMachineType")
    yield
    if original_value is not None:
        await _set_system_param(ws, "CurrentMachineType", original_value)


class TestMachineTypeConstraintEnforcement:
    async def test_machine_type_zero_keeps_compatibility(self, ws, restore_current_machine_type):
        machine_type_id, constraint = await _find_machine_type_constraint(ws, "ref_vel")
        if machine_type_id is None:
            pytest.skip("未找到包含 ref_vel 约束的机种，跳过兼容性用例")

        set_resp = await _set_system_param(ws, "CurrentMachineType", str(machine_type_id))
        assert set_resp.get("success") is True, f"设置 CurrentMachineType 失败: {set_resp}"

        sid = 124
        over_vel = _outside_max(_as_float(constraint.get("maxValue")))
        payload = ScrewSpecFactory.default(sid)
        payload["specification_name"] = "MT-Compat-NoType"
        payload["machine_type_id"] = 0
        payload["detail_params"]["vel_check_enable"] = 0
        payload["step_params"][0]["ref_vel"] = over_vel

        # #region agent log
        _dlog("A", "test_compat:216", "payload_before_save", {
            "vel_check_enable": payload["detail_params"].get("vel_check_enable"),
            "vel_max": payload["detail_params"].get("vel_max"),
            "vel_min": payload["detail_params"].get("vel_min"),
            "ref_vel": payload["step_params"][0].get("ref_vel"),
            "machine_type_id": payload.get("machine_type_id"),
        })
        # #endregion

        resp = await ws.save_screw_param(sid, payload)

        # #region agent log
        _dlog("A", "test_compat:resp", "save_response", {"success": resp.get("success"), "error": resp.get("error", "")})
        # #endregion

        assert resp.get("success") is True, (
            f"machine_type_id=0 应保持兼容并允许保存，实际响应: {resp}"
        )

    async def test_reject_out_of_range_step_ref_vel(self, ws, restore_current_machine_type):
        machine_type_id, constraint = await _find_machine_type_constraint(ws, "ref_vel")
        if machine_type_id is None:
            pytest.skip("未找到包含 ref_vel 约束的机种，跳过越界拒绝用例")

        await _set_system_param(ws, "CurrentMachineType", "0")

        sid = 125
        baseline = ScrewSpecFactory.default(sid)
        baseline["specification_name"] = "MT-Baseline"
        baseline["machine_type_id"] = 0
        baseline_save = await ws.save_screw_param(sid, baseline)
        assert baseline_save.get("success") is True, f"基线保存失败: {baseline_save}"

        over_vel = _outside_max(_as_float(constraint.get("maxValue")))
        payload = ScrewSpecFactory.default(sid)
        payload["specification_name"] = "MT-ShouldReject-RefVel"
        payload["machine_type_id"] = machine_type_id
        await _widen_safety_for_constraints(ws, payload, machine_type_id)
        payload["detail_params"]["vel_max"] = max(payload["detail_params"]["vel_max"], over_vel)
        payload["step_params"][0]["ref_vel"] = over_vel

        resp = await ws.save_screw_param(sid, payload)
        assert resp.get("success") is False, f"ref_vel 越界应被拒绝，实际响应: {resp}"
        err = str(resp.get("error") or resp.get("message") or "").lower()
        assert "ref_vel" in err or "refvel" in err or "速度" in err, f"错误信息应包含 ref_vel/速度，实际: {resp}"

    async def test_reject_ref_vel_does_not_overwrite_existing_values(
        self,
        ws,
        restore_current_machine_type,
    ):
        machine_type_id, constraint = await _find_machine_type_constraint(ws, "ref_vel")
        if machine_type_id is None:
            pytest.skip("未找到包含 ref_vel 约束的机种，跳过不变性用例")

        await _set_system_param(ws, "CurrentMachineType", "0")

        sid = 89
        baseline = ScrewSpecFactory.default(sid)
        baseline["specification_name"] = "MT-Baseline-Immutable-RefVel"
        baseline["machine_type_id"] = 0
        save_r = await ws.save_screw_param(sid, baseline)
        assert save_r.get("success") is True, f"基线保存失败: {save_r}"

        before_detail_r = await ws.get_screw_param(sid)
        before_steps_r = await ws.get_screw_steps(sid)
        assert before_detail_r.get("success") is True, f"读取基线 detail 失败: {before_detail_r}"
        assert before_steps_r.get("success") is True, f"读取基线 steps 失败: {before_steps_r}"
        before_detail_brief = _extract_detail_brief(before_detail_r.get("data", {}))
        before_step0_brief = _extract_step_brief((before_steps_r.get("data") or [{}])[0])

        over_vel = _outside_max(_as_float(constraint.get("maxValue")))
        payload = ScrewSpecFactory.default(sid)
        payload["specification_name"] = "MT-ShouldReject-NoOverwrite-RefVel"
        payload["machine_type_id"] = machine_type_id
        await _widen_safety_for_constraints(ws, payload, machine_type_id)
        payload["detail_params"]["vel_max"] = max(payload["detail_params"]["vel_max"], over_vel)
        payload["step_params"][0]["ref_vel"] = over_vel

        reject_r = await ws.save_screw_param(sid, payload)
        assert reject_r.get("success") is False, f"越界请求应失败，实际: {reject_r}"

        after_detail_r = await ws.get_screw_param(sid)
        after_steps_r = await ws.get_screw_steps(sid)
        assert after_detail_r.get("success") is True, f"读取失败后 detail 失败: {after_detail_r}"
        assert after_steps_r.get("success") is True, f"读取失败后 steps 失败: {after_steps_r}"
        after_detail_brief = _extract_detail_brief(after_detail_r.get("data", {}))
        after_step0_brief = _extract_step_brief((after_steps_r.get("data") or [{}])[0])

        assert after_detail_brief == before_detail_brief, (
            f"拒绝保存后 detail 不应被覆盖: before={before_detail_brief}, after={after_detail_brief}"
        )
        assert after_step0_brief == before_step0_brief, (
            f"拒绝保存后 step 不应被覆盖: before={before_step0_brief}, after={after_step0_brief}"
        )

    async def test_step_ref_vel_accepts_boundary_values(self, ws, restore_current_machine_type):
        machine_type_id, constraint = await _find_machine_type_constraint(ws, "ref_vel")
        if machine_type_id is None:
            pytest.skip("未找到包含 ref_vel 约束的机种，跳过边界通过用例")

        await _set_system_param(ws, "CurrentMachineType", "0")
        min_v = _as_float(constraint.get("minValue"))
        max_v = _as_float(constraint.get("maxValue"))
        if max_v < min_v:
            pytest.skip(f"ref_vel 约束区间非法 [{min_v}, {max_v}]，跳过")

        sid = 95
        for idx, value in enumerate((min_v, max_v), start=1):
            payload = ScrewSpecFactory.default(sid)
            payload["specification_name"] = f"MT-Boundary-RefVel-{idx}"
            payload["machine_type_id"] = machine_type_id
            await _widen_safety_for_constraints(ws, payload, machine_type_id)
            payload["step_params"][0]["ref_vel"] = value

            # #region agent log
            _dlog("C", f"test_boundary_vel:{idx}", "boundary_payload", {
                "ref_vel": value, "vel_min": payload["detail_params"].get("vel_min"),
                "vel_max": payload["detail_params"].get("vel_max"),
                "vel_check_enable": payload["detail_params"].get("vel_check_enable"),
                "constraint_min": min_v, "constraint_max": max_v,
            })
            # #endregion

            resp = await ws.save_screw_param(sid, payload)

            # #region agent log
            _dlog("C", f"test_boundary_vel:resp:{idx}", "boundary_resp", {"success": resp.get("success"), "error": resp.get("error", "")})
            # #endregion

            assert resp.get("success") is True, (
                f"ref_vel 命中边界值 {value} 应允许保存，实际响应: {resp}"
            )

    async def test_step_ref_vel_reject_below_min(self, ws, restore_current_machine_type):
        machine_type_id, constraint = await _find_machine_type_constraint(ws, "ref_vel")
        if machine_type_id is None:
            pytest.skip("未找到包含 ref_vel 约束的机种，跳过下界拒绝用例")

        await _set_system_param(ws, "CurrentMachineType", "0")
        min_v = _as_float(constraint.get("minValue"))
        max_v = _as_float(constraint.get("maxValue"))
        if max_v < min_v:
            pytest.skip(f"ref_vel 约束区间非法 [{min_v}, {max_v}]，跳过")

        sid = 94
        below_vel = _outside_min(min_v)
        payload = ScrewSpecFactory.default(sid)
        payload["specification_name"] = "MT-ShouldReject-RefVel-BelowMin"
        payload["machine_type_id"] = machine_type_id
        await _widen_safety_for_constraints(ws, payload, machine_type_id)
        payload["detail_params"]["vel_min"] = min(payload["detail_params"]["vel_min"], below_vel)
        payload["step_params"][0]["ref_vel"] = below_vel
        resp = await ws.save_screw_param(sid, payload)
        assert resp.get("success") is False, f"ref_vel 低于最小值应被拒绝，实际响应: {resp}"
        err = str(resp.get("error") or resp.get("message") or "").lower()
        assert "ref_vel" in err or "refvel" in err or "速度" in err, f"错误信息应包含 ref_vel/速度，实际: {resp}"

    async def test_non_torque_constraint_null_safe_match_time_target(self, ws, restore_current_machine_type):
        machine_type_id, constraint = await _find_machine_type_constraint(
            ws,
            "time_target",
            require_empty_torque_unit=True,
        )
        if machine_type_id is None:
            pytest.skip("未找到 time_target(空 torqueUnit) 约束，跳过 NULL-safe 命中用例")

        await _set_system_param(ws, "CurrentMachineType", "0")

        sid = 126
        over_time = _outside_max(_as_float(constraint.get("maxValue")))
        payload = ScrewSpecFactory.default(sid)
        payload["specification_name"] = "MT-ShouldReject-TimeTarget"
        payload["machine_type_id"] = machine_type_id
        await _widen_safety_for_constraints(ws, payload, machine_type_id)
        payload["detail_params"]["time_max"] = max(payload["detail_params"]["time_max"], over_time)
        payload["detail_params"]["time_target"] = over_time

        resp = await ws.save_screw_param(sid, payload)
        assert resp.get("success") is False, f"time_target 越界应被拒绝，实际响应: {resp}"
        err = str(resp.get("error") or resp.get("message") or "").lower()
        assert "time_target" in err or "timetarget" in err or "时间" in err, f"错误信息应包含 time_target/时间，实际: {resp}"

    async def test_time_target_accepts_boundary_values(self, ws, restore_current_machine_type):
        matches = await _find_machine_type_constraints(
            ws,
            "time_target",
            require_empty_torque_unit=True,
        )
        machine_type_id, constraint = _pick_constraint_with_valid_range(matches)
        if machine_type_id is None:
            pytest.skip("未找到 time_target(空 torqueUnit) 的有效区间约束，跳过边界通过用例")

        await _set_system_param(ws, "CurrentMachineType", "0")
        min_v = _as_float(constraint.get("minValue"))
        max_v = _as_float(constraint.get("maxValue"))

        sid = 93
        for idx, value in enumerate((min_v, max_v), start=1):
            payload = ScrewSpecFactory.default(sid)
            payload["specification_name"] = f"MT-Boundary-TimeTarget-{idx}"
            payload["machine_type_id"] = machine_type_id
            await _widen_safety_for_constraints(ws, payload, machine_type_id)
            payload["detail_params"]["time_min"] = min(payload["detail_params"]["time_min"], value)
            payload["detail_params"]["time_max"] = max(payload["detail_params"]["time_max"], value)
            payload["detail_params"]["time_target"] = value
            resp = await ws.save_screw_param(sid, payload)
            assert resp.get("success") is True, (
                f"time_target 命中边界值 {value} 应允许保存，实际响应: {resp}"
            )

    async def test_time_target_reject_below_min(self, ws, restore_current_machine_type):
        matches = await _find_machine_type_constraints(
            ws,
            "time_target",
            require_empty_torque_unit=True,
        )
        machine_type_id, constraint = _pick_constraint_with_valid_range(matches)
        if machine_type_id is None:
            pytest.skip("未找到 time_target(空 torqueUnit) 的有效区间约束，跳过下界拒绝用例")

        await _set_system_param(ws, "CurrentMachineType", "0")
        min_v = _as_float(constraint.get("minValue"))

        sid = 92
        below_time = _outside_min(min_v)
        payload = ScrewSpecFactory.default(sid)
        payload["specification_name"] = "MT-ShouldReject-TimeTarget-BelowMin"
        payload["machine_type_id"] = machine_type_id
        await _widen_safety_for_constraints(ws, payload, machine_type_id)
        payload["detail_params"]["time_min"] = min(payload["detail_params"]["time_min"], below_time)
        payload["detail_params"]["time_target"] = below_time
        resp = await ws.save_screw_param(sid, payload)
        assert resp.get("success") is False, f"time_target 低于最小值应被拒绝，实际响应: {resp}"
        err = str(resp.get("error") or resp.get("message") or "").lower()
        assert "time_target" in err or "timetarget" in err or "时间" in err, f"错误信息应包含 time_target/时间，实际: {resp}"

    async def test_reject_time_target_does_not_overwrite_existing_values(
        self,
        ws,
        restore_current_machine_type,
    ):
        matches = await _find_machine_type_constraints(
            ws,
            "time_target",
            require_empty_torque_unit=True,
        )
        machine_type_id, constraint = _pick_constraint_with_valid_range(matches)
        if machine_type_id is None:
            pytest.skip("未找到 time_target(空 torqueUnit) 的有效区间约束，跳过不变性用例")

        await _set_system_param(ws, "CurrentMachineType", "0")

        sid = 88
        baseline = ScrewSpecFactory.default(sid)
        baseline["specification_name"] = "MT-Baseline-Immutable-TimeTarget"
        baseline["machine_type_id"] = 0
        save_r = await ws.save_screw_param(sid, baseline)
        assert save_r.get("success") is True, f"基线保存失败: {save_r}"

        before_detail_r = await ws.get_screw_param(sid)
        before_steps_r = await ws.get_screw_steps(sid)
        assert before_detail_r.get("success") is True, f"读取基线 detail 失败: {before_detail_r}"
        assert before_steps_r.get("success") is True, f"读取基线 steps 失败: {before_steps_r}"
        before_detail_brief = _extract_detail_brief(before_detail_r.get("data", {}))
        before_step0_brief = _extract_step_brief((before_steps_r.get("data") or [{}])[0])

        over_time = _outside_max(_as_float(constraint.get("maxValue")))
        payload = ScrewSpecFactory.default(sid)
        payload["specification_name"] = "MT-ShouldReject-NoOverwrite-TimeTarget"
        payload["machine_type_id"] = machine_type_id
        await _widen_safety_for_constraints(ws, payload, machine_type_id)
        payload["detail_params"]["time_max"] = max(payload["detail_params"]["time_max"], over_time)
        payload["detail_params"]["time_target"] = over_time

        reject_r = await ws.save_screw_param(sid, payload)
        assert reject_r.get("success") is False, f"time_target 越界请求应失败，实际: {reject_r}"

        after_detail_r = await ws.get_screw_param(sid)
        after_steps_r = await ws.get_screw_steps(sid)
        assert after_detail_r.get("success") is True, f"读取失败后 detail 失败: {after_detail_r}"
        assert after_steps_r.get("success") is True, f"读取失败后 steps 失败: {after_steps_r}"
        after_detail_brief = _extract_detail_brief(after_detail_r.get("data", {}))
        after_step0_brief = _extract_step_brief((after_steps_r.get("data") or [{}])[0])

        assert after_detail_brief == before_detail_brief, (
            f"拒绝保存后 detail 不应被覆盖: before={before_detail_brief}, after={after_detail_brief}"
        )
        assert after_step0_brief == before_step0_brief, (
            f"拒绝保存后 step 不应被覆盖: before={before_step0_brief}, after={after_step0_brief}"
        )

    async def test_missing_payload_machine_type_falls_back_to_current_machine_type(
        self,
        ws,
        restore_current_machine_type,
    ):
        machine_type_id, constraint = await _find_machine_type_constraint(ws, "ref_vel")
        if machine_type_id is None:
            pytest.skip("未找到包含 ref_vel 约束的机种，跳过回退用例")

        set_resp = await _set_system_param(ws, "CurrentMachineType", str(machine_type_id))
        assert set_resp.get("success") is True, f"设置 CurrentMachineType 失败: {set_resp}"

        over_vel = _outside_max(_as_float(constraint.get("maxValue")))
        sid = 127
        payload = ScrewSpecFactory.default(sid)
        payload["specification_name"] = "MT-ShouldReject-Fallback"
        payload["machine_type_id"] = machine_type_id
        await _widen_safety_for_constraints(ws, payload, machine_type_id)
        payload.pop("machine_type_id", None)
        payload["detail_params"]["vel_max"] = max(payload["detail_params"]["vel_max"], over_vel)
        payload["step_params"][0]["ref_vel"] = over_vel

        resp = await ws.save_screw_param(sid, payload)
        assert resp.get("success") is False, f"payload 缺失 machine_type_id 时应回退校验并拒绝，实际: {resp}"
        err = str(resp.get("error") or resp.get("message") or "").lower()
        assert "ref_vel" in err or "refvel" in err or "速度" in err, f"错误信息应包含 ref_vel/速度，实际: {resp}"

    async def test_payload_machine_type_id_has_higher_priority_than_current(self, ws, restore_current_machine_type):
        matches = await _find_machine_type_constraints(ws, "ref_vel")
        pair = _pick_two_machine_types_with_different_max(matches)
        if pair is None:
            pytest.skip("未找到两个 ref_vel 上限不同的机种，跳过优先级用例")

        (strict_id, strict_c), (loose_id, loose_c) = pair
        strict_max = _as_float(strict_c.get("maxValue"))
        loose_min = _as_float(loose_c.get("minValue"))
        loose_max = _as_float(loose_c.get("maxValue"))
        if loose_max <= strict_max:
            pytest.skip("无法构造严格/宽松机种差异值，跳过优先级用例")

        candidate = strict_max + max(1.0, (loose_max - strict_max) * 0.5)
        if candidate > loose_max:
            candidate = loose_max
        if candidate < loose_min:
            candidate = loose_min
        if candidate <= strict_max:
            pytest.skip("无法构造只被 payload 机种接受的取值，跳过优先级用例")

        set_resp = await _set_system_param(ws, "CurrentMachineType", str(strict_id))
        assert set_resp.get("success") is True, f"设置 CurrentMachineType 失败: {set_resp}"

        # 查询 loose 机种的全部约束，确保 detail/step 参数都在合法范围内
        loose_constraints_resp = await ws.request(
            {"type": "machine_type_constraints_query", "machineTypeId": loose_id},
            "machine_type_constraints_response",
        )
        loose_constraints = {c["paramName"]: c for c in loose_constraints_resp.get("constraints", [])}

        sid = 91
        payload = ScrewSpecFactory.default(sid)
        payload["specification_name"] = "MT-Payload-Override-Current"
        payload["machine_type_id"] = loose_id
        await _widen_safety_for_constraints(ws, payload, loose_id)
        payload["step_params"][0]["ref_vel"] = candidate

        resp = await ws.save_screw_param(sid, payload)
        assert resp.get("success") is True, (
            f"payload.machine_type_id 应覆盖 CurrentMachineType，实际响应: {resp}"
        )

    async def test_reject_nonexistent_machine_type_id(self, ws, restore_current_machine_type):
        await _set_system_param(ws, "CurrentMachineType", "0")

        sid = 123
        payload = ScrewSpecFactory.default(sid)
        payload["specification_name"] = "MT-ShouldReject-InvalidType"
        payload["machine_type_id"] = 999999

        resp = await ws.save_screw_param(sid, payload)
        assert resp.get("success") is False, f"不存在的 machine_type_id 应被拒绝，实际响应: {resp}"
        err = str(resp.get("error") or resp.get("message") or "").lower()
        assert "machine" in err or "机种" in err, f"错误信息应提示机种ID不存在，实际: {resp}"

    async def test_invalid_current_machine_type_falls_back_to_compatibility(self, ws, restore_current_machine_type):
        set_resp = await _set_system_param(ws, "CurrentMachineType", "INVALID_MT")
        if not set_resp.get("success"):
            pytest.skip(f"系统参数不接受非数字 CurrentMachineType，跳过脏值回退用例: {set_resp}")

        sid = 90
        payload = ScrewSpecFactory.default(sid)
        payload["specification_name"] = "MT-InvalidCurrentType-Fallback"
        payload.pop("machine_type_id", None)
        payload["detail_params"]["vel_check_enable"] = 0
        payload["step_params"][0]["ref_vel"] = 999999
        resp = await ws.save_screw_param(sid, payload)
        assert resp.get("success") is True, (
            f"CurrentMachineType 为脏值时应回退兼容路径并允许保存，实际响应: {resp}"
        )

    async def test_negative_machine_type_id_behaves_as_compatibility(self, ws, restore_current_machine_type):
        sid = 87
        payload = ScrewSpecFactory.default(sid)
        payload["specification_name"] = "MT-NegativeId-Compatibility"
        payload["machine_type_id"] = -1
        payload["detail_params"]["vel_check_enable"] = 0
        payload["step_params"][0]["ref_vel"] = 999999
        resp = await ws.save_screw_param(sid, payload)
        assert resp.get("success") is True, (
            f"machine_type_id<0 应视为回退/兼容路径，实际响应: {resp}"
        )

    async def test_string_machine_type_id_rejected_or_compatibility(self, ws, restore_current_machine_type):
        sid = 86
        payload = ScrewSpecFactory.default(sid)
        payload["specification_name"] = "MT-StringId-Behavior"
        payload["machine_type_id"] = "abc"
        payload["detail_params"]["vel_check_enable"] = 0
        payload["step_params"][0]["ref_vel"] = 999999
        resp = await ws.save_screw_param(sid, payload)

        # 两种可接受语义：
        # 1) 明确拒绝非法类型
        # 2) 解析失败后回退兼容路径并允许保存
        success = bool(resp.get("success"))
        if not success:
            err = str(resp.get("error") or resp.get("message") or "").lower()
            assert ("machine" in err) or ("机种" in err) or ("type" in err), (
                f"字符串 machine_type_id 被拒绝时应返回可定位错误，实际: {resp}"
            )

    async def test_multi_steps_any_out_of_range_step_should_reject_and_keep_data(
        self,
        ws,
        restore_current_machine_type,
    ):
        machine_type_id, constraint = await _find_machine_type_constraint(ws, "ref_vel")
        if machine_type_id is None:
            pytest.skip("未找到 ref_vel 约束，跳过多步骤拒绝用例")

        min_v = _as_float(constraint.get("minValue"))
        max_v = _as_float(constraint.get("maxValue"))
        if max_v < min_v:
            pytest.skip(f"ref_vel 约束区间非法 [{min_v}, {max_v}]，跳过")

        await _set_system_param(ws, "CurrentMachineType", "0")

        sid = 85
        baseline = ScrewSpecFactory.with_steps(sid, 2)
        baseline["specification_name"] = "MT-Baseline-MultiSteps"
        baseline["machine_type_id"] = 0
        baseline["detail_params"]["vel_check_enable"] = 0
        baseline["step_params"][0]["ref_vel"] = min_v
        baseline["step_params"][1]["ref_vel"] = max_v
        base_r = await ws.save_screw_param(sid, baseline)
        assert base_r.get("success") is True, f"多步骤基线保存失败: {base_r}"

        before_steps_r = await ws.get_screw_steps(sid)
        assert before_steps_r.get("success") is True, f"读取基线 steps 失败: {before_steps_r}"
        before_steps_brief = _extract_steps_brief_list(before_steps_r.get("data", []))
        assert len(before_steps_brief) >= 2, f"预期至少 2 个步骤，实际: {before_steps_r}"

        over_vel = _outside_max(max_v)
        payload = ScrewSpecFactory.with_steps(sid, 2)
        payload["specification_name"] = "MT-ShouldReject-MultiStep-SecondInvalid"
        payload["machine_type_id"] = machine_type_id
        await _widen_safety_for_constraints(ws, payload, machine_type_id)
        payload["detail_params"]["vel_max"] = max(payload["detail_params"]["vel_max"], over_vel)
        payload["step_params"][0]["ref_vel"] = min_v
        payload["step_params"][1]["ref_vel"] = over_vel
        reject_r = await ws.save_screw_param(sid, payload)
        assert reject_r.get("success") is False, f"任一步越界应整体拒绝，实际: {reject_r}"

        after_steps_r = await ws.get_screw_steps(sid)
        assert after_steps_r.get("success") is True, f"读取失败后 steps 失败: {after_steps_r}"
        after_steps_brief = _extract_steps_brief_list(after_steps_r.get("data", []))
        assert after_steps_brief == before_steps_brief, (
            f"整体拒绝后 steps 不应被覆盖: before={before_steps_brief}, after={after_steps_brief}"
        )

    async def test_multi_steps_all_boundary_values_should_pass(self, ws, restore_current_machine_type):
        machine_type_id, constraint = await _find_machine_type_constraint(ws, "ref_vel")
        if machine_type_id is None:
            pytest.skip("未找到 ref_vel 约束，跳过多步骤边界通过用例")

        min_v = _as_float(constraint.get("minValue"))
        max_v = _as_float(constraint.get("maxValue"))
        if max_v < min_v:
            pytest.skip(f"ref_vel 约束区间非法 [{min_v}, {max_v}]，跳过")

        await _set_system_param(ws, "CurrentMachineType", "0")

        sid = 84
        payload = ScrewSpecFactory.with_steps(sid, 2)
        payload["specification_name"] = "MT-MultiSteps-Boundary-Pass"
        payload["machine_type_id"] = machine_type_id
        await _widen_safety_for_constraints(ws, payload, machine_type_id)
        payload["step_params"][0]["ref_vel"] = min_v
        payload["step_params"][1]["ref_vel"] = max_v
        resp = await ws.save_screw_param(sid, payload)
        assert resp.get("success") is True, f"多步骤全边界值应通过，实际: {resp}"

    async def test_step_ref_time_constraint_boundaries_and_reject(self, ws, restore_current_machine_type):
        matches = await _find_machine_type_constraints(
            ws,
            "time",
            require_empty_torque_unit=True,
        )
        machine_type_id, constraint = _pick_constraint_with_valid_range(matches)
        if machine_type_id is None:
            pytest.skip("未找到 step ref_time 对应的 time 约束，跳过 ref_time 用例")

        min_v = _as_float(constraint.get("minValue"))
        max_v = _as_float(constraint.get("maxValue"))
        if max_v < min_v:
            pytest.skip(f"time 约束区间非法 [{min_v}, {max_v}]，跳过")

        await _set_system_param(ws, "CurrentMachineType", "0")

        sid = 83
        # 边界通过
        for idx, value in enumerate((min_v, max_v), start=1):
            payload = ScrewSpecFactory.default(sid)
            payload["specification_name"] = f"MT-RefTime-Boundary-{idx}"
            payload["machine_type_id"] = machine_type_id
            payload["step_params"][0]["ref_time"] = value
            pass_r = await ws.save_screw_param(sid, payload)
            assert pass_r.get("success") is True, (
                f"ref_time 边界值 {value} 应通过，实际: {pass_r}"
            )

        # 越界拒绝（> max）
        payload = ScrewSpecFactory.default(sid)
        payload["specification_name"] = "MT-RefTime-ShouldReject-AboveMax"
        payload["machine_type_id"] = machine_type_id
        payload["step_params"][0]["ref_time"] = _outside_max(max_v)
        reject_r = await ws.save_screw_param(sid, payload)
        assert reject_r.get("success") is False, f"ref_time 超上限应拒绝，实际: {reject_r}"
        err = str(reject_r.get("error") or reject_r.get("message") or "").lower()
        assert ("time" in err) or ("ref_time" in err), f"错误信息应包含 time/ref_time，实际: {reject_r}"

    async def test_step_ref_degree_constraint_boundaries_and_reject(self, ws, restore_current_machine_type):
        matches = await _find_machine_type_constraints(
            ws,
            "ref_degree",
            require_empty_torque_unit=True,
        )
        machine_type_id, constraint = _pick_constraint_with_valid_range(matches)
        if machine_type_id is None:
            pytest.skip("未找到 step ref_degree 约束，跳过 ref_degree 用例")

        min_v = _as_float(constraint.get("minValue"))
        max_v = _as_float(constraint.get("maxValue"))
        if max_v < min_v:
            pytest.skip(f"ref_degree 约束区间非法 [{min_v}, {max_v}]，跳过")

        await _set_system_param(ws, "CurrentMachineType", "0")

        sid = 82
        for idx, value in enumerate((min_v, max_v), start=1):
            payload = ScrewSpecFactory.default(sid)
            payload["specification_name"] = f"MT-RefDegree-Boundary-{idx}"
            payload["machine_type_id"] = machine_type_id
            await _widen_safety_for_constraints(ws, payload, machine_type_id)
            payload["detail_params"]["degree_min"] = min(payload["detail_params"]["degree_min"], value)
            payload["detail_params"]["degree_max"] = max(payload["detail_params"]["degree_max"], value)
            payload["step_params"][0]["ref_degree"] = value
            pass_r = await ws.save_screw_param(sid, payload)
            assert pass_r.get("success") is True, (
                f"ref_degree 边界值 {value} 应通过，实际: {pass_r}"
            )

        over_deg = _outside_max(max_v)
        payload = ScrewSpecFactory.default(sid)
        payload["specification_name"] = "MT-RefDegree-ShouldReject-AboveMax"
        payload["machine_type_id"] = machine_type_id
        await _widen_safety_for_constraints(ws, payload, machine_type_id)
        payload["detail_params"]["degree_max"] = max(payload["detail_params"]["degree_max"], over_deg)
        payload["step_params"][0]["ref_degree"] = over_deg
        reject_r = await ws.save_screw_param(sid, payload)
        assert reject_r.get("success") is False, f"ref_degree 超上限应拒绝，实际: {reject_r}"
        err = str(reject_r.get("error") or reject_r.get("message") or "").lower()
        assert ("ref_degree" in err) or ("degree" in err) or ("角度" in err), f"错误信息应包含 ref_degree/degree/角度，实际: {reject_r}"

    async def test_step_ref_torque_constraint_boundaries_and_reject(self, ws, restore_current_machine_type):
        matches = await _find_machine_type_constraints(
            ws,
            "torque",
            require_empty_torque_unit=False,
        )
        machine_type_id, constraint, torque_unit_code = _pick_torque_constraint_with_mappable_unit(matches)
        if machine_type_id is None:
            pytest.skip("未找到可映射扭矩单位的 torque 约束，跳过 ref_torque 用例")

        min_v = _as_float(constraint.get("minValue"))
        max_v = _as_float(constraint.get("maxValue"))
        if max_v < min_v:
            pytest.skip(f"torque 约束区间非法 [{min_v}, {max_v}]，跳过")

        await _set_system_param(ws, "CurrentMachineType", "0")

        # 查询该机种的 clamp_torque 约束，确保 detail 扭矩参数也在约束范围内
        constraints_resp = await ws.request(
            {"type": "machine_type_constraints_query", "machineTypeId": machine_type_id},
            "machine_type_constraints_response",
        )
        all_constraints = {c["paramName"]: c for c in constraints_resp.get("constraints", [])}
        cmin_c = all_constraints.get("clamp_torque_min")
        cmax_c = all_constraints.get("clamp_torque_max")
        mid_v = (min_v + max_v) / 2

        sid = 81
        for idx, value in enumerate((min_v, max_v), start=1):
            payload = ScrewSpecFactory.default(sid)
            payload["specification_name"] = f"MT-RefTorque-Boundary-{idx}"
            payload["machine_type_id"] = machine_type_id
            await _widen_safety_for_constraints(ws, payload, machine_type_id)
            payload["step_params"][0]["ref_torque"] = value
            pass_r = await ws.save_screw_param(sid, payload)
            assert pass_r.get("success") is True, (
                f"ref_torque 边界值 {value} 应通过，实际: {pass_r}"
            )

        over_torque = _outside_max(max_v)
        payload = ScrewSpecFactory.default(sid)
        payload["specification_name"] = "MT-RefTorque-ShouldReject-AboveMax"
        payload["machine_type_id"] = machine_type_id
        await _widen_safety_for_constraints(ws, payload, machine_type_id)
        payload["detail_params"]["torque_max"] = max(payload["detail_params"]["torque_max"], over_torque)
        payload["step_params"][0]["ref_torque"] = over_torque
        reject_r = await ws.save_screw_param(sid, payload)
        assert reject_r.get("success") is False, f"ref_torque 超上限应拒绝，实际: {reject_r}"
        err = str(reject_r.get("error") or reject_r.get("message") or "").lower()
        assert "torque" in err or "扭" in err, f"错误信息应包含 torque/扭，实际: {reject_r}"

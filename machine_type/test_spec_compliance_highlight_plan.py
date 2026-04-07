"""螺丝规格机种合规高亮/过滤方案回归测试。

覆盖点（对应 screw_spec_compliance_highlight 计划）：
1) spec_compliance_query 可拉取当前缓存
2) CurrentMachineType 变更触发全量重建并推送 spec_compliance_update
3) screw_param_config 触发单规格合规状态更新
4) screw_spec_set_active 激活/停用触发缓存增删
5) 多客户端均可收到合规推送
6) active + compliant 交集可作为默认螺丝下拉候选（前端过滤语义）
"""

from __future__ import annotations

import asyncio
import time

import pytest

from lib.constants import MsgType
from lib.helpers import ScrewSpecFactory

pytestmark = [pytest.mark.machine_type, pytest.mark.p0]

_SID_COMPLIANT = 110
_SID_NON_COMPLIANT = 111
_SID_SAVE_TRIGGER = 112

_COMPLIANCE_EVENT_TYPES = {"spec_compliance_update", "spec_compliance_query_response"}

_TORQUE_UNIT_MAP = {"mN.m": 0, "kgf.cm": 1, "lbf.in": 2, "N.m": 3}


def _as_float(value, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _extract_system_param_value(system_params_resp: dict, param_name: str) -> str | None:
    payload = system_params_resp.get("data", system_params_resp)
    if isinstance(payload, list):
        for item in payload:
            if item.get("param_name") == param_name or item.get("paramName") == param_name:
                return item.get("param_value") or item.get("paramValue")
    if isinstance(payload, dict):
        return payload.get(param_name)
    return None


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y")
    return False


def _extract_compliance_map(message: dict) -> dict[int, bool]:
    def _candidate_maps(node):
        if isinstance(node, dict):
            yield node
            for v in node.values():
                if isinstance(v, dict):
                    yield v

    for candidate in _candidate_maps(message):
        out: dict[int, bool] = {}
        for k, v in candidate.items():
            try:
                sid = int(k)
            except (TypeError, ValueError):
                continue
            out[sid] = _to_bool(v)
        if out:
            return out
    return {}


async def _set_system_param(ws, param_name: str, value: str) -> dict:
    msg = {
        "type": MsgType.SYSTEM_PARAM_UPDATE,
        "param_name": param_name,
        "param_value": str(value),
        "modify_user": "test",
    }
    return await ws.request(msg, MsgType.SYSTEM_PARAM_UPDATE_RESPONSE)


async def _set_active(ws, spec_id: int, is_active: bool) -> dict:
    return await ws.request(
        {
            "type": MsgType.SPEC_SET_ACTIVE,
            "spec_id": spec_id,
            "is_active": bool(is_active),
        },
        MsgType.SPEC_SET_ACTIVE_RESPONSE,
    )


async def _wait_compliance_event(ws, send_ts: float, timeout: float = 6.0) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout
    next_idx = ws.events.count
    while asyncio.get_event_loop().time() < deadline:
        events = await ws.events.get_all()
        for ev in events[next_idx:]:
            next_idx += 1
            if ev.get("type") not in _COMPLIANCE_EVENT_TYPES:
                continue
            if ev.get("_received_at", 0) <= send_ts:
                continue
            return ev
        await asyncio.sleep(0.05)
    raise TimeoutError(f"No compliance event received within {timeout:.1f}s")


async def _query_compliance_map(ws, timeout: float = 6.0) -> dict[int, bool]:
    send_ts = time.monotonic()
    await ws.send({"type": "spec_compliance_query"})
    msg = await _wait_compliance_event(ws, send_ts, timeout=timeout)
    return _extract_compliance_map(msg)


# ── 机种约束查询工具 ──────────────────────────────────────────────


async def _get_all_constraints_map(ws, machine_type_id: int, preferred_torque_unit: str = "kgf.cm") -> dict[str, dict]:
    """获取指定机种的全部约束，返回 {paramName: constraint_dict}。

    对于 torque 等有多个 torqueUnit 行的参数，优先选择 preferred_torque_unit 对应的行。
    默认 kgf.cm 与 ScrewSpecFactory.default 的 torque_unit=1 一致。
    """
    resp = await ws.request(
        {"type": "machine_type_constraints_query", "machineTypeId": machine_type_id},
        "machine_type_constraints_response",
    )
    result: dict[str, dict] = {}
    if resp.get("success"):
        for c in resp.get("constraints", []):
            name = c.get("paramName")
            if not name:
                continue
            if name in result:
                existing_unit = result[name].get("torqueUnit")
                new_unit = c.get("torqueUnit")
                if existing_unit == preferred_torque_unit:
                    continue
                if new_unit == preferred_torque_unit:
                    result[name] = c
            else:
                result[name] = c
    return result


async def _find_machine_type_constraints(ws, param_name: str) -> list[tuple[int, dict]]:
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
            min_v = _as_float(c.get("minValue"))
            max_v = _as_float(c.get("maxValue"))
            if max_v < min_v:
                continue
            matches.append((machine_type_id, c))
    return matches


def _pick_two_machine_types_with_different_max(
    matches: list[tuple[int, dict]],
) -> tuple[tuple[int, dict], tuple[int, dict]] | None:
    normalized: list[tuple[int, dict, float]] = []
    for machine_type_id, c in matches:
        max_v = _as_float(c.get("maxValue"))
        normalized.append((machine_type_id, c, max_v))

    if len(normalized) < 2:
        return None

    normalized.sort(key=lambda x: x[2])
    strict = normalized[0]
    loose = normalized[-1]
    if loose[2] <= strict[2]:
        return None
    return (strict[0], strict[1]), (loose[0], loose[1])


def _apply_torque_and_vel_constraints(
    payload: dict,
    constraints: dict[str, dict],
    ref_vel_override: float | None = None,
) -> None:
    """将扭矩和速度相关参数设到机种约束范围内。

    复用 test_machine_type_constraint_enforcement.py 中验证过的模式（第 514-546 行）。
    只修改约束涉及的参数，其余保持 ScrewSpecFactory.default 的安全默认值。
    """
    dp = payload["detail_params"]
    sp = payload["step_params"][0]

    tc = constraints.get("torque")
    if tc:
        t_min = _as_float(tc.get("minValue"))
        t_max = _as_float(tc.get("maxValue"))
        t_mid = (t_min + t_max) / 2
        dp["torque_target"] = t_mid
        dp["torque_min"] = t_min
        dp["torque_max"] = t_max
        sp["ref_torque"] = t_mid

    cmin_c = constraints.get("clamp_torque_min")
    cmax_c = constraints.get("clamp_torque_max")
    if cmin_c:
        dp["clamp_torque_min"] = _as_float(cmin_c.get("minValue"))
    if cmax_c:
        dp["clamp_torque_max"] = _as_float(cmax_c.get("maxValue"))

    if ref_vel_override is not None:
        sp["ref_vel"] = ref_vel_override
        dp["vel_target"] = ref_vel_override
        dp["vel_max"] = max(dp.get("vel_max", 300), ref_vel_override)
        dp["vel_min"] = min(dp.get("vel_min", 100), ref_vel_override)
        sp["to_vel"] = ref_vel_override


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
async def restore_current_machine_type(ws):
    original_params = await ws.get_system_params()
    original_value = _extract_system_param_value(original_params, "CurrentMachineType")
    yield
    if original_value is not None:
        await _set_system_param(ws, "CurrentMachineType", original_value)


@pytest.fixture
async def ensure_specs_inactive(ws):
    for sid in (_SID_COMPLIANT, _SID_NON_COMPLIANT, _SID_SAVE_TRIGGER):
        await _set_active(ws, sid, False)
    yield
    for sid in (_SID_COMPLIANT, _SID_NON_COMPLIANT, _SID_SAVE_TRIGGER):
        await _set_active(ws, sid, False)


# ── 测试用例 ─────────────────────────────────────────────────────


class TestSpecCompliancePlan:

    @pytest.mark.smoke
    async def test_spec_compliance_query_returns_boolean_map(self, ws):
        compliance = await _query_compliance_map(ws)
        assert isinstance(compliance, dict), f"spec_compliance_query 应返回 map，实际: {compliance!r}"
        for sid, ok in compliance.items():
            assert 0 <= sid <= 127, f"spec id 应在 0..127，实际: {sid}"
            assert isinstance(ok, bool), f"合规值应为 bool，实际: sid={sid}, value={ok!r}"

    async def test_machine_type_change_rebuilds_cache_and_pushes_update(
        self,
        ws,
        restore_current_machine_type,
        ensure_specs_inactive,
    ):
        """切换机种后合规性缓存全量重建。

        1. 找到 strict / loose 两个机种（ref_vel 上限不同）
        2. 构造一个在 loose 下合规但 strict 下不合规的规格
        3. 先在 loose 下验证合规 → 切到 strict → 验证不合规
        """
        matches = await _find_machine_type_constraints(ws, "ref_vel")
        pair = _pick_two_machine_types_with_different_max(matches)
        if pair is None:
            pytest.skip("未找到 max(ref_vel) 不同的两个机种，跳过重建触发用例")

        (strict_id, strict_c), (loose_id, loose_c) = pair
        strict_max = _as_float(strict_c.get("maxValue"))
        loose_min = _as_float(loose_c.get("minValue"))
        loose_max = _as_float(loose_c.get("maxValue"))

        candidate = strict_max + max(1.0, (loose_max - strict_max) * 0.5)
        candidate = min(loose_max, max(loose_min, candidate))
        if candidate <= strict_max:
            pytest.skip("无法构造 strict 拒绝 / loose 通过的 ref_vel 值")

        loose_constraints = await _get_all_constraints_map(ws, loose_id)

        payload = ScrewSpecFactory.default(_SID_NON_COMPLIANT)
        payload["specification_name"] = "CMP-Rebuild-Case"
        payload["machine_type_id"] = loose_id
        _apply_torque_and_vel_constraints(payload, loose_constraints, ref_vel_override=candidate)

        await _set_system_param(ws, "CurrentMachineType", str(loose_id))
        save_r = await ws.save_screw_param(_SID_NON_COMPLIANT, payload)
        assert save_r.get("success") is True, f"准备测试规格失败: {save_r}"
        # saveScrewParamsToDB 内部已调用 ensureSpecActive，无需再次 _set_active

        await asyncio.sleep(0.3)
        map_loose = await _query_compliance_map(ws)
        assert map_loose.get(_SID_NON_COMPLIANT) is True, (
            f"在宽松机种下应合规，实际: sid={_SID_NON_COMPLIANT}, map={map_loose}"
        )

        send_ts = time.monotonic()
        set_strict = await _set_system_param(ws, "CurrentMachineType", str(strict_id))
        assert set_strict.get("success") is True, f"设置严格机种失败: {set_strict}"
        await _wait_compliance_event(ws, send_ts)
        map_strict = await _query_compliance_map(ws)
        assert map_strict.get(_SID_NON_COMPLIANT) is False, (
            f"切到严格机种后应变为不合规，实际: sid={_SID_NON_COMPLIANT}, map={map_strict}"
        )

    async def test_save_updates_single_spec_compliance(
        self,
        ws,
        restore_current_machine_type,
        ensure_specs_inactive,
    ):
        """保存规格后合规性缓存增量更新。

        1. 在 strict 机种下保存一个合规规格 → 缓存 True
        2. 用 machine_type_id=0 保存同一规格，ref_vel 超出 strict → 缓存变 False
        """
        matches = await _find_machine_type_constraints(ws, "ref_vel")
        pair = _pick_two_machine_types_with_different_max(matches)
        if pair is None:
            pytest.skip("未找到 max(ref_vel) 不同的两个机种，跳过保存触发用例")

        (strict_id, strict_c), (loose_id, loose_c) = pair
        strict_max = _as_float(strict_c.get("maxValue"))
        loose_max = _as_float(loose_c.get("maxValue"))
        loose_min = _as_float(loose_c.get("minValue"))

        candidate = strict_max + max(1.0, (loose_max - strict_max) * 0.5)
        candidate = min(loose_max, max(loose_min, candidate))
        if candidate <= strict_max:
            pytest.skip("无法构造 strict 拒绝 / loose 通过的 ref_vel 值")

        # 步骤 1：在 strict 机种下保存合规规格
        set_mt = await _set_system_param(ws, "CurrentMachineType", str(strict_id))
        assert set_mt.get("success") is True, f"设置 CurrentMachineType 失败: {set_mt}"

        strict_constraints = await _get_all_constraints_map(ws, strict_id)
        payload_ok = ScrewSpecFactory.default(_SID_SAVE_TRIGGER)
        payload_ok["specification_name"] = "CMP-Save-OK"
        payload_ok["machine_type_id"] = strict_id
        _apply_torque_and_vel_constraints(payload_ok, strict_constraints)
        save_ok = await ws.save_screw_param(_SID_SAVE_TRIGGER, payload_ok)
        assert save_ok.get("success") is True, f"保存合规规格失败: {save_ok}"

        # saveScrewParamsToDB 内部已调用 ensureSpecActive，无需再次 _set_active
        # 注意：setSpecActive(true) 会重置参数为默认值，覆盖刚保存的数据
        await asyncio.sleep(0.3)
        map_before = await _query_compliance_map(ws)
        assert map_before.get(_SID_SAVE_TRIGGER) is True, (
            f"合规保存后缓存应为 True，实际: {map_before}"
        )

        # 步骤 2：用 machine_type_id=0 绕过保存校验，写入超出 strict 的 ref_vel
        loose_constraints = await _get_all_constraints_map(ws, loose_id)
        send_ts = time.monotonic()
        payload_ng = ScrewSpecFactory.default(_SID_SAVE_TRIGGER)
        payload_ng["specification_name"] = "CMP-Save-NG"
        payload_ng["machine_type_id"] = 0
        _apply_torque_and_vel_constraints(payload_ng, loose_constraints, ref_vel_override=candidate)
        save_ng = await ws.save_screw_param(_SID_SAVE_TRIGGER, payload_ng)
        assert save_ng.get("success") is True, f"用 machine_type_id=0 保存应成功: {save_ng}"
        await _wait_compliance_event(ws, send_ts)

        map_after = await _query_compliance_map(ws)
        assert map_after.get(_SID_SAVE_TRIGGER) is False, (
            "保存超出当前机种约束的参数后，合规性缓存应更新为 False。"
            f" 实际 map={map_after}"
        )

    async def test_activate_deactivate_updates_cache_membership(
        self,
        ws,
        restore_current_machine_type,
        ensure_specs_inactive,
    ):
        matches = await _find_machine_type_constraints(ws, "ref_vel")
        if not matches:
            pytest.skip("未找到 ref_vel 约束，跳过激活/停用触发用例")

        machine_type_id, c = matches[0]
        set_mt = await _set_system_param(ws, "CurrentMachineType", str(machine_type_id))
        assert set_mt.get("success") is True, f"设置 CurrentMachineType 失败: {set_mt}"

        all_constraints = await _get_all_constraints_map(ws, machine_type_id)
        payload = ScrewSpecFactory.default(_SID_COMPLIANT)
        payload["specification_name"] = "CMP-Activate-Case"
        payload["machine_type_id"] = machine_type_id
        _apply_torque_and_vel_constraints(payload, all_constraints)
        save_r = await ws.save_screw_param(_SID_COMPLIANT, payload)
        assert save_r.get("success") is True, f"准备测试规格失败: {save_r}"

        send_ts = time.monotonic()
        deact = await _set_active(ws, _SID_COMPLIANT, False)
        assert deact.get("success") is True, f"停用失败: {deact}"
        await asyncio.sleep(0.5)
        map_deact = await _query_compliance_map(ws)
        assert _SID_COMPLIANT not in map_deact, (
            f"停用后缓存应移除规格 id={_SID_COMPLIANT}，实际: {map_deact}"
        )

        send_ts = time.monotonic()
        act = await _set_active(ws, _SID_COMPLIANT, True)
        assert act.get("success") is True, f"激活失败: {act}"
        await _wait_compliance_event(ws, send_ts)

        map_act = await _query_compliance_map(ws)
        assert _SID_COMPLIANT in map_act, (
            f"激活后缓存应包含规格 id={_SID_COMPLIANT}，实际: {map_act}"
        )

    async def test_broadcast_reaches_other_clients_after_machine_type_change(
        self,
        ws_pair,
        restore_current_machine_type,
    ):
        ws_a, ws_b = ws_pair
        matches = await _find_machine_type_constraints(ws_a, "ref_vel")
        pair = _pick_two_machine_types_with_different_max(matches)
        if pair is None:
            pytest.skip("未找到可切换的机种对，跳过多客户端广播用例")

        (strict_id, _), (loose_id, _) = pair
        await ws_b.events.clear()

        await _set_system_param(ws_a, "CurrentMachineType", str(loose_id))
        send_ts = time.monotonic()
        set_r = await _set_system_param(ws_a, "CurrentMachineType", str(strict_id))
        assert set_r.get("success") is True, f"切换机种失败: {set_r}"

        event_b = await _wait_compliance_event(ws_b, send_ts)
        assert event_b.get("type") in _COMPLIANCE_EVENT_TYPES, (
            f"客户端B应收到合规推送，实际: {event_b}"
        )

    async def test_active_and_compliant_intersection_matches_dropdown_semantics(
        self,
        ws,
        restore_current_machine_type,
        ensure_specs_inactive,
    ):
        matches = await _find_machine_type_constraints(ws, "ref_vel")
        pair = _pick_two_machine_types_with_different_max(matches)
        if pair is None:
            pytest.skip("未找到 max(ref_vel) 不同的机种对，跳过下拉过滤语义用例")

        (strict_id, strict_c), (loose_id, loose_c) = pair
        strict_max = _as_float(strict_c.get("maxValue"))
        loose_min = _as_float(loose_c.get("minValue"))
        loose_max = _as_float(loose_c.get("maxValue"))
        candidate = strict_max + max(1.0, (loose_max - strict_max) * 0.5)
        candidate = min(loose_max, max(loose_min, candidate))
        if candidate <= strict_max:
            pytest.skip("无法构造一合规一不合规的 ref_vel 候选值")

        strict_constraints = await _get_all_constraints_map(ws, strict_id)
        loose_constraints = await _get_all_constraints_map(ws, loose_id)

        # 合规样本：在 strict 机种下保存
        payload_ok = ScrewSpecFactory.default(_SID_COMPLIANT)
        payload_ok["specification_name"] = "CMP-Filter-OK"
        payload_ok["machine_type_id"] = strict_id
        _apply_torque_and_vel_constraints(payload_ok, strict_constraints)
        await _set_system_param(ws, "CurrentMachineType", str(strict_id))
        save_ok = await ws.save_screw_param(_SID_COMPLIANT, payload_ok)
        assert save_ok.get("success") is True, f"保存合规样本失败: {save_ok}"

        # 不合规样本：用 machine_type_id=0 绕过校验，ref_vel 超出 strict
        payload_ng = ScrewSpecFactory.default(_SID_NON_COMPLIANT)
        payload_ng["specification_name"] = "CMP-Filter-NG"
        payload_ng["machine_type_id"] = 0
        _apply_torque_and_vel_constraints(payload_ng, loose_constraints, ref_vel_override=candidate)
        await _set_system_param(ws, "CurrentMachineType", "0")
        save_ng = await ws.save_screw_param(_SID_NON_COMPLIANT, payload_ng)
        assert save_ng.get("success") is True, f"保存不合规样本失败: {save_ng}"

        # saveScrewParamsToDB 内部已调用 ensureSpecActive，无需再次 _set_active
        # setSpecActive(true) 会重置参数为默认值

        set_mt = await _set_system_param(ws, "CurrentMachineType", str(strict_id))
        assert set_mt.get("success") is True, f"设置严格机种失败: {set_mt}"

        await asyncio.sleep(0.5)
        compliance = await _query_compliance_map(ws)

        assert compliance.get(_SID_COMPLIANT) is True, (
            f"合规样本应为 True，实际: {compliance}"
        )
        assert compliance.get(_SID_NON_COMPLIANT) is False, (
            f"不合规样本应为 False，实际: {compliance}"
        )

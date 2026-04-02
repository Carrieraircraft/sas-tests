"""螺丝规格参数保存测试（Update / auto-activate）

覆盖：
  - 正常保存（默认参数、单步骤、最大步骤数）
  - auto-activate：保存后规格自动出现在激活列表（ensureSpecActive 逻辑）
  - 服务端主动推送 screw_specification_options_get_response
  - Roundtrip：写入值与读回值一致
  - 边界/错误：缺少必填字段、越界 ID、步骤数超限
  - 性能：单次保存响应时间

测试 ID 全部取自 SAFE_TEST_RANGE (100-127)。
"""

import pytest

from lib.constants import MsgType, SAFE_TEST_RANGE, MAX_STEPS_PER_SPEC, MAX_SINGLE_RESPONSE_MS
from lib.helpers import ScrewSpecFactory, assert_response_time

pytestmark = [pytest.mark.spec128, pytest.mark.p1]

# 专用 ID，按测试类分段，避免并发干扰
_SID_BASIC_DEFAULT  = 110
_SID_BASIC_1STEP    = 111
_SID_BASIC_MAXSTEP  = 112
_SID_AUTO_ACTIVATE  = 113
_SID_OPTIONS_PUSH   = 114
_SID_ROUNDTRIP_NAME = 115
_SID_ROUNDTRIP_PROG = 116
_SID_ROUNDTRIP_STEP = 117
_SID_PERF           = 118


# ── 辅助 ──────────────────────────────────────────────────────────────────────


async def _activate(ws, spec_id: int) -> None:
    """确保规格处于激活状态（预置条件）。"""
    await ws.request(
        {"type": MsgType.SPEC_SET_ACTIVE, "spec_id": spec_id, "is_active": True},
        MsgType.SPEC_SET_ACTIVE_RESPONSE,
    )


async def _deactivate(ws, spec_id: int) -> None:
    """停用规格（清理）。"""
    await ws.request(
        {"type": MsgType.SPEC_SET_ACTIVE, "spec_id": spec_id, "is_active": False},
        MsgType.SPEC_SET_ACTIVE_RESPONSE,
    )


# ── 正常保存 ──────────────────────────────────────────────────────────────────


class TestSaveBasic:
    async def test_save_default_params(self, ws):
        """先激活槽位，再保存默认参数，响应 success=True。"""
        sid = _SID_BASIC_DEFAULT
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.default(sid)
            resp = await ws.save_screw_param(sid, payload)
            assert resp.get("success") is True, f"save failed: {resp}"
            assert resp.get("specification_id") == sid
        finally:
            await _deactivate(ws, sid)

    async def test_save_with_1_step(self, ws):
        """保存只含 1 个步骤的规格，响应 success=True。"""
        sid = _SID_BASIC_1STEP
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.with_steps(sid, 1)
            resp = await ws.save_screw_param(sid, payload)
            assert resp.get("success") is True, f"save 1-step failed: {resp}"
        finally:
            await _deactivate(ws, sid)

    async def test_save_with_max_steps(self, ws):
        """保存含最大步骤数（MAX_STEPS_PER_SPEC）的规格，响应 success=True。"""
        sid = _SID_BASIC_MAXSTEP
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.with_steps(sid, MAX_STEPS_PER_SPEC)
            resp = await ws.save_screw_param(sid, payload)
            assert resp.get("success") is True, f"save max-steps failed: {resp}"
        finally:
            await _deactivate(ws, sid)

    async def test_save_auto_activates_spec_in_list(self, ws):
        """直接保存未激活的规格（不先调 set_active），
        ensureSpecActive 应自动将其激活，规格出现在激活列表中。"""
        sid = _SID_AUTO_ACTIVATE
        # 确保初始为停用状态
        await _deactivate(ws, sid)

        # 直接保存，不先激活
        payload = ScrewSpecFactory.default(sid)
        resp = await ws.save_screw_param(sid, payload)
        assert resp.get("success") is True, f"save failed: {resp}"

        # 验证规格已在激活列表中
        specs = await ws.get_spec_list()
        active_ids = {s["value"] for s in specs if s.get("isActive")}
        assert sid in active_ids, (
            f"spec_id={sid} should be auto-activated after save, "
            f"active ids: {sorted(active_ids)}"
        )

        # 清理
        await _deactivate(ws, sid)

    async def test_save_triggers_options_push(self, ws):
        """保存成功后，服务端应主动推送 screw_specification_options_get_response。"""
        sid = _SID_OPTIONS_PUSH
        await _activate(ws, sid)
        try:
            # 预先注册对 options_response 的等待
            push_task = ws._ensure_queue(MsgType.SPEC_OPTIONS_RESPONSE)

            payload = ScrewSpecFactory.default(sid)
            # save_screw_param 等待 SCREW_PARAM_SAVE_RESPONSE
            resp = await ws.save_screw_param(sid, payload)
            assert resp.get("success") is True

            # 等待服务端推送规格列表（后端在 sendScrewParamConfigResponse 成功路径触发）
            import asyncio
            try:
                push = await asyncio.wait_for(push_task.get(), timeout=5.0)
                assert push.get("type") == MsgType.SPEC_OPTIONS_RESPONSE
                assert push.get("success") is True
                assert isinstance(push.get("data"), list)
            except asyncio.TimeoutError:
                pytest.fail("server did not push screw_specification_options_get_response after save")
        finally:
            await _deactivate(ws, sid)


# ── Roundtrip ────────────────────────────────────────────────────────────────


class TestSaveRoundtrip:
    async def test_name_roundtrip(self, ws):
        """保存特定名称后，get_screw_param 应返回相同的规格名称。"""
        sid = _SID_ROUNDTRIP_NAME
        await _activate(ws, sid)
        try:
            name = f"RoundtripName-{sid}"
            payload = ScrewSpecFactory.default(sid)
            payload["specification_name"] = name
            save_r = await ws.save_screw_param(sid, payload)
            assert save_r.get("success") is True

            get_r = await ws.get_screw_param(sid)
            assert get_r.get("success") is True
            data = get_r.get("data", {})
            assert data.get("screw_name") == name, (
                f"expected name '{name}', got '{data.get('screw_name')}'"
            )
        finally:
            await _deactivate(ws, sid)

    async def test_prog_cnt_roundtrip(self, ws):
        """保存 prog_cnt=3 后，get_screw_param 读回值应等于 3。"""
        sid = _SID_ROUNDTRIP_PROG
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.with_steps(sid, 3)
            save_r = await ws.save_screw_param(sid, payload)
            assert save_r.get("success") is True

            get_r = await ws.get_screw_param(sid)
            assert get_r.get("success") is True
            assert get_r["data"]["prog_cnt"] == 3, (
                f"expected prog_cnt=3, got {get_r['data'].get('prog_cnt')}"
            )
        finally:
            await _deactivate(ws, sid)

    async def test_step_torque_roundtrip(self, ws):
        """写入步骤 ref_torque=0.55 后，get_screw_steps 读回值应接近 0.55。"""
        sid = _SID_ROUNDTRIP_STEP
        ref_torque = 0.55
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.with_steps(sid, 1)
            payload["step_params"][0]["ref_torque"] = ref_torque
            save_r = await ws.save_screw_param(sid, payload)
            assert save_r.get("success") is True

            step_r = await ws.get_screw_steps(sid)
            assert step_r.get("success") is True
            steps = step_r.get("data", [])
            assert len(steps) >= 1, "expected at least 1 step"
            got_torque = steps[0].get("ref_torque", None)
            assert got_torque is not None, "ref_torque missing in step response"
            assert abs(got_torque - ref_torque) < 0.01, (
                f"expected ref_torque≈{ref_torque}, got {got_torque}"
            )
        finally:
            await _deactivate(ws, sid)

    async def test_screw_cnt_roundtrip(self, ws):
        """写入 screw_cnt=12 后，读回值应等于 12。"""
        sid = 119
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.default(sid)
            payload["detail_params"]["screw_cnt"] = 12
            save_r = await ws.save_screw_param(sid, payload)
            assert save_r.get("success") is True

            get_r = await ws.get_screw_param(sid)
            assert get_r.get("success") is True
            assert get_r["data"]["screw_cnt"] == 12, (
                f"expected screw_cnt=12, got {get_r['data'].get('screw_cnt')}"
            )
        finally:
            await _deactivate(ws, sid)


# ── 边界与错误 ────────────────────────────────────────────────────────────────


class TestSaveEdge:
    async def test_missing_detail_params_rejected(self, ws):
        """缺少 detail_params 字段，应被后端拒绝，返回 success=False。"""
        resp = await ws.request(
            {
                "type": MsgType.SCREW_PARAM_CONFIG,
                "mode": 1,
                "specification_id": 120,
                "specification_name": "MissingDetail",
                # 故意省略 detail_params
            },
            MsgType.SCREW_PARAM_SAVE_RESPONSE,
        )
        assert resp.get("success") is False, f"expected failure, got: {resp}"
        assert resp.get("error"), "error message should be present"

    async def test_invalid_spec_id_rejected(self, ws):
        """specification_id=200 超出 0-127 范围，应被拒绝。"""
        payload = ScrewSpecFactory.default(200)
        resp = await ws.request(payload, MsgType.SCREW_PARAM_SAVE_RESPONSE)
        assert resp.get("success") is False, f"expected failure for spec_id=200, got: {resp}"

    async def test_too_many_steps_handled(self, ws):
        """step_params 超过最大步骤数（MAX_STEPS_PER_SPEC+1），应被截断或拒绝，不崩溃。"""
        sid = 121
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.with_steps(sid, MAX_STEPS_PER_SPEC + 1)
            # 后端截断或返回 success=False 均可接受，不应超时或崩溃
            resp = await ws.save_screw_param(sid, payload)
            assert "success" in resp, "response must contain 'success' field"
        finally:
            await _deactivate(ws, sid)

    async def test_save_complex_full_params(self, ws):
        """保存带全量参数（complex_full）的规格，响应 success=True。"""
        sid = 122
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.complex_full(sid)
            resp = await ws.save_screw_param(sid, payload)
            assert resp.get("success") is True, f"complex_full save failed: {resp}"
        finally:
            await _deactivate(ws, sid)

    async def test_overwrite_existing_spec(self, ws):
        """对已有参数的规格再次保存（覆盖写），应成功。"""
        sid = 123
        await _activate(ws, sid)
        try:
            first = ScrewSpecFactory.with_steps(sid, 2)
            r1 = await ws.save_screw_param(sid, first)
            assert r1.get("success") is True

            second = ScrewSpecFactory.with_steps(sid, 4)
            r2 = await ws.save_screw_param(sid, second)
            assert r2.get("success") is True, f"overwrite failed: {r2}"

            get_r = await ws.get_screw_param(sid)
            assert get_r["data"]["prog_cnt"] == 4
        finally:
            await _deactivate(ws, sid)


# ── 性能 ─────────────────────────────────────────────────────────────────────


class TestSavePerformance:
    async def test_save_response_time(self, ws):
        """单次保存响应时间应小于 MAX_SINGLE_RESPONSE_MS（含 MCU 写入）。
        注意：实际写 MCU 耗时较长，此处使用宽松阈值 500ms。"""
        sid = _SID_PERF
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.default(sid)
            await ws.save_screw_param(sid, payload)
            assert_response_time(ws.last_elapsed_ms, 500)
        finally:
            await _deactivate(ws, sid)

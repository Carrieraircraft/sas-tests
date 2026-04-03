"""参数关联校验与安全开关清零回归测试。

覆盖目标（对应方案“参数关联校验与安全开关清零”）：
1) 安全开关关闭时，target/min/max 强制清零（后端兜底）
2) 安全开关开启时，步骤参数不得超过安全窗口
3) 其他参数关系与范围校验（免检步数、降速阈值、倾角、紧固次数）
"""

from __future__ import annotations

import pytest

from lib.helpers import ScrewSpecFactory

pytestmark = [pytest.mark.spec128, pytest.mark.p0]

_SID_SAFETY_ZERO = 96
_SID_RELATION_REJECT = 97
_SID_OTHER_VALIDATION = 98


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


def _error_text(resp: dict) -> str:
    return str(resp.get("error") or resp.get("message") or "").lower()


def _assert_rejected(resp: dict, *keywords: str) -> None:
    assert resp.get("success") is False, f"expected rejection, got: {resp}"
    if keywords:
        err = _error_text(resp)
        assert any(k.lower() in err for k in keywords), (
            f"error should contain one of {keywords}, got: {resp}"
        )


class TestSafetySwitchForceZero:
    async def test_disable_all_safety_checks_forces_window_to_zero(self, ws):
        sid = _SID_SAFETY_ZERO
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.default(sid)
            payload["machine_type_id"] = 0
            d = payload["detail_params"]

            # 时间窗口
            d["time_check_enable"] = 0
            d["time_target"] = 1234
            d["time_min"] = 1000
            d["time_max"] = 1500

            # 扭矩窗口
            d["torque_check_enable"] = 0
            d["torque_target"] = 0.33
            d["torque_min"] = 0.25
            d["torque_max"] = 0.40

            # 速度窗口
            d["vel_check_enable"] = 0
            d["vel_target"] = 500
            d["vel_min"] = 300
            d["vel_max"] = 800

            # 角度窗口
            d["degree_check_enable"] = 0
            d["degree_target"] = 360
            d["degree_min"] = 180
            d["degree_max"] = 720

            save_r = await ws.save_screw_param(sid, payload)
            assert save_r.get("success") is True, f"save failed: {save_r}"

            read_r = await ws.get_screw_param(sid)
            assert read_r.get("success") is True, f"read failed: {read_r}"
            data = read_r.get("data", {})

            assert float(data.get("time_target", -1)) == 0
            assert float(data.get("time_min", -1)) == 0
            assert float(data.get("time_max", -1)) == 0

            assert float(data.get("torque_target", -1)) == 0
            assert float(data.get("torque_min", -1)) == 0
            assert float(data.get("torque_max", -1)) == 0

            assert float(data.get("vel_target", -1)) == 0
            assert float(data.get("vel_min", -1)) == 0
            assert float(data.get("vel_max", -1)) == 0

            assert float(data.get("degree_target", -1)) == 0
            assert float(data.get("degree_min", -1)) == 0
            assert float(data.get("degree_max", -1)) == 0
        finally:
            await _deactivate(ws, sid)


class TestStepSafetyRelation:
    async def test_reject_step_torque_above_enabled_safety_max(self, ws):
        sid = _SID_RELATION_REJECT
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.default(sid)
            payload["machine_type_id"] = 0
            d = payload["detail_params"]
            d["torque_check_enable"] = 1
            d["torque_min"] = 0.20
            d["torque_target"] = 0.25
            d["torque_max"] = 0.30
            payload["step_params"][0]["ref_torque"] = 0.31

            resp = await ws.save_screw_param(sid, payload)
            _assert_rejected(resp, "torque", "扭矩", "扭力")
        finally:
            await _deactivate(ws, sid)

    async def test_reject_step_time_above_enabled_safety_max(self, ws):
        sid = _SID_RELATION_REJECT
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.default(sid)
            payload["machine_type_id"] = 0
            d = payload["detail_params"]
            d["time_check_enable"] = 1
            d["time_min"] = 100
            d["time_target"] = 200
            d["time_max"] = 250
            payload["step_params"][0]["ref_time"] = 260

            resp = await ws.save_screw_param(sid, payload)
            _assert_rejected(resp, "time", "时间")
        finally:
            await _deactivate(ws, sid)


class TestOtherParamValidation:
    @pytest.mark.parametrize(
        "field,value,keywords",
        [
            ("prog_start_valid_step", 2, ("prog", "免检")),
            ("vel_limit_torque_percent", 101, ("percent", "阈值")),
            ("gyrometer_start_angle", 91, ("gyrometer", "倾角")),
            ("gyrometer_stop_angle", 91, ("gyrometer", "倾角")),
            ("confirm_cnt", 0, ("confirm", "紧固次数")),
        ],
    )
    async def test_reject_invalid_detail_param_values(self, ws, field, value, keywords):
        sid = _SID_OTHER_VALIDATION
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.default(sid)
            payload["machine_type_id"] = 0
            d = payload["detail_params"]
            d[field] = value

            # 免检步数校验依赖 prog_cnt，显式构造 ">= prog_cnt" 触发场景
            if field == "prog_start_valid_step":
                d["prog_cnt"] = 2

            resp = await ws.save_screw_param(sid, payload)
            _assert_rejected(resp, *keywords)
        finally:
            await _deactivate(ws, sid)


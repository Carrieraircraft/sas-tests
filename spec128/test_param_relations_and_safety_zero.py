"""参数关联校验与安全开关清零回归测试。

覆盖目标（对应方案“参数关联校验与安全开关清零”）：
1) 安全开关关闭时，target/min/max 强制清零（后端兜底）
2) 安全开关开启时，步骤参数不得超过安全窗口
3) 其他参数关系与范围校验（免检步数、降速阈值、倾角、紧固次数）
4) 步骤完成检测条件校验（ok_if 位标志合法性与非免检步骤必须设置检测条件）
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


_SID_OK_IF = 99


class TestStepCompletionCondition:
    """步骤完成检测条件（ok_if）校验：位标志合法性 + 非免检步骤必须设置。"""

    async def test_reject_invalid_ok_if_flag_value(self, ws):
        """ok_if 包含无效位标志（如 16=0x10），应被拒绝。"""
        sid = _SID_OK_IF
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.default(sid)
            payload["step_params"][0]["ok_if_1"] = 16

            resp = await ws.save_screw_param(sid, payload)
            _assert_rejected(resp, "检测条件", "标志位", "ok_if")
        finally:
            await _deactivate(ws, sid)

    async def test_reject_all_ok_if_zero_on_valid_step(self, ws):
        """非免检步骤 ok_if 全为 0（无任何完成条件），应被拒绝。"""
        sid = _SID_OK_IF
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.default(sid)
            payload["detail_params"]["prog_start_valid_step"] = 0
            payload["step_params"][0]["ok_if_1"] = 0
            payload["step_params"][0]["ok_if_2"] = 0
            payload["step_params"][0]["ok_if_3"] = 0
            payload["step_params"][0]["ok_if_4"] = 0

            resp = await ws.save_screw_param(sid, payload)
            _assert_rejected(resp, "检测条件", "至少")
        finally:
            await _deactivate(ws, sid)

    async def test_accept_ok_if_zero_on_exempt_step(self, ws):
        """免检步骤（index < prog_start_valid_step）ok_if 全为 0，应允许保存。"""
        sid = _SID_OK_IF
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.with_steps(sid, 2)
            payload["detail_params"]["prog_start_valid_step"] = 1
            # 步骤0 在免检范围内，ok_if 全 0 应被接受
            payload["step_params"][0]["ok_if_1"] = 0
            payload["step_params"][0]["ok_if_2"] = 0
            payload["step_params"][0]["ok_if_3"] = 0
            payload["step_params"][0]["ok_if_4"] = 0
            # 步骤1 是非免检步骤，保持有效检测条件
            payload["step_params"][1]["ok_if_1"] = 2

            resp = await ws.save_screw_param(sid, payload)
            assert resp.get("success") is True, f"免检步骤 ok_if 全 0 应被接受: {resp}"
        finally:
            await _deactivate(ws, sid)

    async def test_accept_single_ok_if_flag(self, ws):
        """只设置一个有效的 ok_if（如仅扭力），应允许保存。"""
        sid = _SID_OK_IF
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.default(sid)
            payload["step_params"][0]["ok_if_1"] = 2  # 仅扭力
            payload["step_params"][0]["ok_if_2"] = 0
            payload["step_params"][0]["ok_if_3"] = 0
            payload["step_params"][0]["ok_if_4"] = 0

            resp = await ws.save_screw_param(sid, payload)
            assert resp.get("success") is True, f"单个有效检测条件应被接受: {resp}"
        finally:
            await _deactivate(ws, sid)

    @pytest.mark.parametrize("bad_value", [16, 32, 64, 128, 255])
    async def test_reject_various_invalid_ok_if_values(self, ws, bad_value):
        """各种无效 ok_if 值（组合位标志、超范围值）均应被拒绝。"""
        sid = _SID_OK_IF
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.default(sid)
            payload["step_params"][0]["ok_if_1"] = bad_value

            resp = await ws.save_screw_param(sid, payload)
            _assert_rejected(resp, "检测条件", "标志位", "ok_if")
        finally:
            await _deactivate(ws, sid)

    @pytest.mark.parametrize("combo_value", [3, 5, 6, 9, 10, 12, 7, 11, 13, 14, 15])
    async def test_accept_combined_ok_if_flags(self, ws, combo_value):
        """ok_if 槽位可以是多个条件的组合（位或），合法组合应被接受。"""
        sid = _SID_OK_IF
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.default(sid)
            payload["step_params"][0]["ok_if_1"] = combo_value

            resp = await ws.save_screw_param(sid, payload)
            assert resp.get("success") is True, f"ok_if 组合值 {combo_value} 应被接受: {resp}"
        finally:
            await _deactivate(ws, sid)

    async def test_accept_all_four_valid_flags(self, ws):
        """四个 ok_if 分别设置速度/扭力/角度/时间（1/2/4/8），应成功。"""
        sid = _SID_OK_IF
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.default(sid)
            payload["step_params"][0]["ok_if_1"] = 1  # 速度
            payload["step_params"][0]["ok_if_2"] = 2  # 扭力
            payload["step_params"][0]["ok_if_3"] = 4  # 角度
            payload["step_params"][0]["ok_if_4"] = 8  # 时间

            resp = await ws.save_screw_param(sid, payload)
            assert resp.get("success") is True, f"四个合法检测条件应被接受: {resp}"
        finally:
            await _deactivate(ws, sid)

    async def test_reject_second_step_missing_ok_if(self, ws):
        """多步骤规格中，第二步（非免检）ok_if 全 0 时应被拒绝。"""
        sid = _SID_OK_IF
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.with_steps(sid, 2)
            payload["detail_params"]["prog_start_valid_step"] = 0
            # 步骤0 有效
            payload["step_params"][0]["ok_if_1"] = 2
            # 步骤1 无检测条件
            payload["step_params"][1]["ok_if_1"] = 0
            payload["step_params"][1]["ok_if_2"] = 0
            payload["step_params"][1]["ok_if_3"] = 0
            payload["step_params"][1]["ok_if_4"] = 0

            resp = await ws.save_screw_param(sid, payload)
            _assert_rejected(resp, "步骤2", "检测条件", "至少")
        finally:
            await _deactivate(ws, sid)


_SID_PARTIAL_UPDATE = 94


class TestPartialUpdateValidation:
    """只更新 detail_params 不传（或传空）step_params 时，
    后端应加载数据库已有步骤参与校验，防止安全窗口缩小后旧步骤参数越界。"""

    async def test_reject_detail_only_update_when_steps_exceed_new_safety(self, ws):
        """先存高扭力步骤，再只更新 detail 降低 torque_max，不传 step_params，应被拒绝。"""
        sid = _SID_PARTIAL_UPDATE
        await _activate(ws, sid)
        try:
            base = ScrewSpecFactory.default(sid)
            base["detail_params"]["torque_check_enable"] = 1
            base["detail_params"]["torque_min"] = 0.5
            base["detail_params"]["torque_target"] = 1.0
            base["detail_params"]["torque_max"] = 2.0
            base["step_params"][0]["ref_torque"] = 1.8
            resp1 = await ws.save_screw_param(sid, base)
            assert resp1.get("success") is True, f"初始保存失败: {resp1}"

            update = ScrewSpecFactory.default(sid)
            update["detail_params"]["torque_check_enable"] = 1
            update["detail_params"]["torque_min"] = 0.1
            update["detail_params"]["torque_target"] = 0.3
            update["detail_params"]["torque_max"] = 0.4
            del update["step_params"]

            resp2 = await ws.save_screw_param(sid, update)
            _assert_rejected(resp2, "扭力", "torque", "上界")
        finally:
            await _deactivate(ws, sid)

    async def test_reject_empty_steps_update_when_steps_exceed_new_safety(self, ws):
        """同上场景，但传空 step_params=[]，也应被拒绝。"""
        sid = _SID_PARTIAL_UPDATE
        await _activate(ws, sid)
        try:
            base = ScrewSpecFactory.default(sid)
            base["detail_params"]["torque_check_enable"] = 1
            base["detail_params"]["torque_min"] = 0.5
            base["detail_params"]["torque_target"] = 1.0
            base["detail_params"]["torque_max"] = 2.0
            base["step_params"][0]["ref_torque"] = 1.8
            resp1 = await ws.save_screw_param(sid, base)
            assert resp1.get("success") is True, f"初始保存失败: {resp1}"

            update = ScrewSpecFactory.default(sid)
            update["detail_params"]["torque_check_enable"] = 1
            update["detail_params"]["torque_min"] = 0.1
            update["detail_params"]["torque_target"] = 0.3
            update["detail_params"]["torque_max"] = 0.4
            update["step_params"] = []

            resp2 = await ws.save_screw_param(sid, update)
            _assert_rejected(resp2, "扭力", "torque", "上界")
        finally:
            await _deactivate(ws, sid)

    async def test_accept_detail_only_update_when_steps_within_new_safety(self, ws):
        """先存低扭力步骤，再只更新 detail 安全窗口也够大，应通过。"""
        sid = _SID_PARTIAL_UPDATE
        await _activate(ws, sid)
        try:
            base = ScrewSpecFactory.default(sid)
            base["detail_params"]["torque_check_enable"] = 1
            base["detail_params"]["torque_min"] = 0.1
            base["detail_params"]["torque_target"] = 0.3
            base["detail_params"]["torque_max"] = 0.5
            base["step_params"][0]["ref_torque"] = 0.3
            resp1 = await ws.save_screw_param(sid, base)
            assert resp1.get("success") is True, f"初始保存失败: {resp1}"

            update = ScrewSpecFactory.default(sid)
            update["detail_params"]["torque_check_enable"] = 1
            update["detail_params"]["torque_min"] = 0.2
            update["detail_params"]["torque_target"] = 0.35
            update["detail_params"]["torque_max"] = 0.5
            del update["step_params"]

            resp2 = await ws.save_screw_param(sid, update)
            assert resp2.get("success") is True, f"安全窗口内更新 detail 应成功: {resp2}"
        finally:
            await _deactivate(ws, sid)


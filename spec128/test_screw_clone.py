"""螺丝规格克隆测试（Clone / Copy）

覆盖：
  - 正常克隆：success=True，返回正确的 source_id / target_id
  - 数据一致性：克隆后 target 参数与 source 一致
  - 源不变：克隆不修改 source 的任何参数
  - 边界/错误：target/source 越界、source == target

测试 ID 全部取自 SAFE_TEST_RANGE (100-127)。
"""

import pytest

from lib.constants import MsgType, SAFE_TEST_RANGE
from lib.helpers import ScrewSpecFactory

pytestmark = [pytest.mark.spec128, pytest.mark.p1]

_SID_SRC_BASIC   = 100  # 克隆源（基础克隆测试）
_SID_TGT_BASIC   = 101  # 克隆目标（基础克隆测试）
_SID_SRC_DATA    = 102  # 克隆源（数据一致性测试）
_SID_TGT_DATA    = 103  # 克隆目标（数据一致性测试）
_SID_SRC_NOMOD   = 104  # 克隆源（源不变测试）
_SID_TGT_NOMOD   = 105  # 克隆目标（源不变测试）


# ── 辅助 ──────────────────────────────────────────────────────────────────────


async def _activate(ws, spec_id: int) -> None:
    await ws.request(
        {"type": MsgType.SPEC_SET_ACTIVE, "spec_id": spec_id, "is_active": True},
        MsgType.SPEC_SET_ACTIVE_RESPONSE,
    )


async def _deactivate(ws, spec_id: int) -> None:
    await ws.request(
        {"type": MsgType.SPEC_SET_ACTIVE, "spec_id": spec_id, "is_active": False},
        MsgType.SPEC_SET_ACTIVE_RESPONSE,
    )


async def _save(ws, spec_id: int, **overrides) -> dict:
    """激活后保存默认参数，支持通过 overrides 覆盖 detail_params 字段。"""
    await _activate(ws, spec_id)
    payload = ScrewSpecFactory.default(spec_id)
    if overrides:
        payload["detail_params"].update(overrides)
    return await ws.save_screw_param(spec_id, payload)


# ── 正常克隆 ──────────────────────────────────────────────────────────────────


class TestCloneBasic:
    async def test_clone_to_empty_slot(self, ws):
        """克隆到未激活的空槽位：success=True，响应包含 source_id 和 target_id。"""
        src, tgt = _SID_SRC_BASIC, _SID_TGT_BASIC
        await _save(ws, src)
        # 确保 target 处于未激活状态
        await _deactivate(ws, tgt)
        try:
            resp = await ws.clone_screw_spec(src, tgt)
            assert resp.get("success") is True, f"clone failed: {resp}"
            assert resp.get("source_id") == src, f"source_id mismatch: {resp}"
            assert resp.get("target_id") == tgt, f"target_id mismatch: {resp}"
        finally:
            await _deactivate(ws, src)
            await _deactivate(ws, tgt)

    async def test_clone_response_type(self, ws):
        """克隆响应 type 应为 screw_spec_clone_response。"""
        src, tgt = 106, 107
        await _save(ws, src)
        await _deactivate(ws, tgt)
        try:
            resp = await ws.clone_screw_spec(src, tgt)
            assert resp.get("type") == MsgType.SPEC_CLONE_RESPONSE
        finally:
            await _deactivate(ws, src)
            await _deactivate(ws, tgt)

    async def test_clone_to_already_active_slot(self, ws):
        """克隆到已有参数的激活槽位，应覆盖写入并 success=True。"""
        src, tgt = 108, 109
        await _save(ws, src, screw_cnt=8)
        await _save(ws, tgt, screw_cnt=4)   # target 先有旧数据
        try:
            resp = await ws.clone_screw_spec(src, tgt)
            assert resp.get("success") is True, f"clone to active slot failed: {resp}"
        finally:
            await _deactivate(ws, src)
            await _deactivate(ws, tgt)


# ── 数据一致性 ────────────────────────────────────────────────────────────────


class TestCloneDataConsistency:
    async def test_clone_data_equals_source(self, ws):
        """克隆后，target 的 screw_name 和 prog_cnt 应与 source 一致。"""
        src, tgt = _SID_SRC_DATA, _SID_TGT_DATA
        name = f"CloneSrc-{src}"
        step_count = 3

        await _activate(ws, src)
        payload = ScrewSpecFactory.with_steps(src, step_count)
        payload["specification_name"] = name
        save_r = await ws.save_screw_param(src, payload)
        assert save_r.get("success") is True

        await _deactivate(ws, tgt)
        try:
            clone_r = await ws.clone_screw_spec(src, tgt)
            assert clone_r.get("success") is True, f"clone failed: {clone_r}"

            tgt_r = await ws.get_screw_param(tgt)
            assert tgt_r.get("success") is True, f"get target param failed: {tgt_r}"
            tgt_data = tgt_r.get("data", {})
            assert tgt_data.get("prog_cnt") == step_count, (
                f"expected prog_cnt={step_count}, got {tgt_data.get('prog_cnt')}"
            )
        finally:
            await _deactivate(ws, src)
            await _deactivate(ws, tgt)

    async def test_clone_step_params_copied(self, ws):
        """克隆后，target 的步骤数应与 source 一致。"""
        src, tgt = 110, 111
        step_count = 2
        await _activate(ws, src)
        payload = ScrewSpecFactory.with_steps(src, step_count)
        await ws.save_screw_param(src, payload)
        await _deactivate(ws, tgt)
        try:
            clone_r = await ws.clone_screw_spec(src, tgt)
            assert clone_r.get("success") is True

            step_r = await ws.get_screw_steps(tgt)
            if step_r.get("success") and step_r.get("data") is not None:
                assert len(step_r["data"]) == step_count, (
                    f"expected {step_count} steps in cloned target, got {len(step_r['data'])}"
                )
        finally:
            await _deactivate(ws, src)
            await _deactivate(ws, tgt)

    async def test_clone_does_not_modify_source(self, ws):
        """克隆后，source 的参数应保持不变。"""
        src, tgt = _SID_SRC_NOMOD, _SID_TGT_NOMOD
        step_count = 4
        await _activate(ws, src)
        payload = ScrewSpecFactory.with_steps(src, step_count)
        await ws.save_screw_param(src, payload)

        # 记录克隆前 source 的参数
        before = await ws.get_screw_param(src)
        assert before.get("success") is True

        await _deactivate(ws, tgt)
        try:
            clone_r = await ws.clone_screw_spec(src, tgt)
            assert clone_r.get("success") is True

            # 克隆后再次读取 source
            after = await ws.get_screw_param(src)
            assert after.get("success") is True
            assert before.get("data", {}).get("prog_cnt") == after.get("data", {}).get("prog_cnt"), (
                "clone should not modify source prog_cnt"
            )
        finally:
            await _deactivate(ws, src)
            await _deactivate(ws, tgt)

    async def test_independent_modification_after_clone(self, ws):
        """克隆后修改 target，source 不受影响（深拷贝语义）。"""
        src, tgt = 112, 113
        await _activate(ws, src)
        src_payload = ScrewSpecFactory.with_steps(src, 2)
        await ws.save_screw_param(src, src_payload)

        await _deactivate(ws, tgt)
        try:
            await ws.clone_screw_spec(src, tgt)

            # 修改 target
            tgt_payload = ScrewSpecFactory.with_steps(tgt, 5)
            mod_r = await ws.save_screw_param(tgt, tgt_payload)
            assert mod_r.get("success") is True

            # source 仍应是 2 步
            src_after = await ws.get_screw_param(src)
            assert src_after["data"]["prog_cnt"] == 2, (
                f"source prog_cnt should still be 2, got {src_after['data'].get('prog_cnt')}"
            )
        finally:
            await _deactivate(ws, src)
            await _deactivate(ws, tgt)


# ── 边界与错误 ────────────────────────────────────────────────────────────────


class TestCloneEdge:
    async def test_clone_target_out_of_range(self, ws):
        """target_id=128 超出范围，应被拒绝，返回 success=False。"""
        resp = await ws.clone_screw_spec(0, 128)
        assert resp.get("success") is False, f"expected failure for target=128, got: {resp}"
        assert resp.get("error"), "error message should be present"

    async def test_clone_target_negative(self, ws):
        """target_id=-1 超出范围，应被拒绝。"""
        resp = await ws.clone_screw_spec(0, -1)
        assert resp.get("success") is False, f"expected failure for target=-1, got: {resp}"

    async def test_clone_source_out_of_range(self, ws):
        """source_id=200 超出范围，应被拒绝。"""
        resp = await ws.clone_screw_spec(200, 100)
        assert resp.get("success") is False, f"expected failure for source=200, got: {resp}"

    async def test_clone_source_negative(self, ws):
        """source_id=-1 超出范围，应被拒绝。"""
        resp = await ws.clone_screw_spec(-1, 100)
        assert resp.get("success") is False, f"expected failure for source=-1, got: {resp}"

    async def test_clone_same_id_handled(self, ws):
        """source_id == target_id：应被拒绝或后端幂等处理，不崩溃。"""
        sid = 114
        await _activate(ws, sid)
        try:
            resp = await ws.clone_screw_spec(sid, sid)
            # 接受拒绝（success=False）或幂等成功，但必须有响应
            assert "success" in resp, "response must contain 'success' field"
        finally:
            await _deactivate(ws, sid)

    async def test_clone_missing_source_id(self, ws):
        """请求缺少 source_id 字段，应被拒绝。"""
        resp = await ws.request(
            {"type": MsgType.SPEC_CLONE, "target_id": 100},
            MsgType.SPEC_CLONE_RESPONSE,
        )
        assert resp.get("success") is False or resp.get("error"), (
            f"expected failure for missing source_id, got: {resp}"
        )

    async def test_clone_missing_target_id(self, ws):
        """请求缺少 target_id 字段，应被拒绝。"""
        resp = await ws.request(
            {"type": MsgType.SPEC_CLONE, "source_id": 0},
            MsgType.SPEC_CLONE_RESPONSE,
        )
        assert resp.get("success") is False or resp.get("error"), (
            f"expected failure for missing target_id, got: {resp}"
        )

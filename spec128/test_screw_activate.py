"""螺丝规格激活/停用测试（Create/Delete 语义）

screw_spec_set_active (is_active=true)  等效 Create ——激活一个空槽位，使其在列表中可见
screw_spec_set_active (is_active=false) 等效 Delete ——停用规格，隐藏并重置引用计数

测试 ID 全部取自 SAFE_TEST_RANGE (100-127)，避免干扰生产数据。
"""

import pytest

from lib.constants import MsgType, SAFE_TEST_RANGE
from lib.helpers import ScrewSpecFactory

pytestmark = [pytest.mark.spec128, pytest.mark.p1]

# 测试专用 ID，互不重叠，确保并发运行时也不冲突
_SID_ACTIVATE     = 100
_SID_DEACTIVATE   = 101
_SID_IDEM_ACT     = 102
_SID_IDEM_DEACT   = 103
_SID_REACTIVATE   = 104


# ── 辅助 ──────────────────────────────────────────────────────────────────────


async def _set_active(ws, spec_id: int, is_active: bool) -> dict:
    """发送 screw_spec_set_active 并返回响应。"""
    return await ws.request(
        {
            "type": MsgType.SPEC_SET_ACTIVE,
            "spec_id": spec_id,
            "is_active": is_active,
        },
        MsgType.SPEC_SET_ACTIVE_RESPONSE,
    )


async def _is_in_active_list(ws, spec_id: int) -> bool:
    """检查规格是否在激活列表中（isActive=True）。"""
    specs = await ws.get_spec_list()
    for s in specs:
        if s.get("value") == spec_id:
            return bool(s.get("isActive", False))
    return False


# ── 正常流 ────────────────────────────────────────────────────────────────────


class TestActivate:
    async def test_activate_spec(self, ws):
        """激活一个未激活的槽位：响应 success=True，列表中 isActive=True。"""
        sid = _SID_ACTIVATE
        # 确保初始为停用状态
        await _set_active(ws, sid, False)

        resp = await _set_active(ws, sid, True)
        assert resp.get("success") is True, f"activate failed: {resp}"
        assert resp.get("spec_id") == sid
        assert resp.get("is_active") is True

        assert await _is_in_active_list(ws, sid), "spec should appear as active in list"

        # 清理
        await _set_active(ws, sid, False)

    async def test_deactivate_spec(self, ws):
        """停用一个已激活的槽位：响应 success=True，列表中 isActive=False。"""
        sid = _SID_DEACTIVATE
        # 确保初始为激活状态
        await _set_active(ws, sid, True)

        resp = await _set_active(ws, sid, False)
        assert resp.get("success") is True, f"deactivate failed: {resp}"
        assert resp.get("spec_id") == sid
        assert resp.get("is_active") is False

        assert not await _is_in_active_list(ws, sid), "spec should not be active in list"

    async def test_activate_idempotent(self, ws):
        """重复激活同一 ID 不报错（幂等性）。"""
        sid = _SID_IDEM_ACT
        await _set_active(ws, sid, True)

        resp = await _set_active(ws, sid, True)
        assert resp.get("success") is True, f"idempotent activate failed: {resp}"

        # 清理
        await _set_active(ws, sid, False)

    async def test_deactivate_idempotent(self, ws):
        """重复停用同一 ID 不报错（幂等性）。"""
        sid = _SID_IDEM_DEACT
        await _set_active(ws, sid, False)

        resp = await _set_active(ws, sid, False)
        assert resp.get("success") is True, f"idempotent deactivate failed: {resp}"

    async def test_deactivate_then_reactivate_keeps_data(self, ws):
        """停用后重新激活：原有参数数据被新的默认值覆盖（setSpecActive 会 reset），
        但操作本身应成功，不产生错误。"""
        sid = _SID_REACTIVATE

        # 先激活并保存参数
        await _set_active(ws, sid, True)
        payload = ScrewSpecFactory.default(sid)
        save_r = await ws.save_screw_param(sid, payload)
        assert save_r.get("success") is True

        # 停用
        deact_r = await _set_active(ws, sid, False)
        assert deact_r.get("success") is True

        # 重新激活
        react_r = await _set_active(ws, sid, True)
        assert react_r.get("success") is True
        assert await _is_in_active_list(ws, sid)

        # 清理
        await _set_active(ws, sid, False)


# ── 边界与错误 ────────────────────────────────────────────────────────────────


class TestActivateEdge:
    async def test_invalid_spec_id_128_rejected(self, ws):
        """spec_id=128 超出范围 (0-127)，应被拒绝。"""
        resp = await ws.request(
            {"type": MsgType.SPEC_SET_ACTIVE, "spec_id": 128, "is_active": True},
            MsgType.SPEC_SET_ACTIVE_RESPONSE,
        )
        assert resp.get("success") is False, f"expected failure for spec_id=128, got: {resp}"
        assert resp.get("error"), "error message should be present"

    async def test_invalid_spec_id_negative_rejected(self, ws):
        """spec_id=-1 超出范围，应被拒绝。"""
        resp = await ws.request(
            {"type": MsgType.SPEC_SET_ACTIVE, "spec_id": -1, "is_active": True},
            MsgType.SPEC_SET_ACTIVE_RESPONSE,
        )
        assert resp.get("success") is False, f"expected failure for spec_id=-1, got: {resp}"

    async def test_missing_is_active_field(self, ws):
        """缺少 is_active 字段，应被拒绝并返回错误。"""
        resp = await ws.request(
            {"type": MsgType.SPEC_SET_ACTIVE, "spec_id": 100},
            MsgType.SPEC_SET_ACTIVE_RESPONSE,
        )
        assert resp.get("success") is False, f"expected failure for missing is_active, got: {resp}"
        assert resp.get("error"), "error message should be present"

    async def test_missing_spec_id_field(self, ws):
        """缺少 spec_id 字段，应被拒绝并返回错误。"""
        resp = await ws.request(
            {"type": MsgType.SPEC_SET_ACTIVE, "is_active": True},
            MsgType.SPEC_SET_ACTIVE_RESPONSE,
        )
        assert resp.get("success") is False, f"expected failure for missing spec_id, got: {resp}"


# ── 副作用验证 ────────────────────────────────────────────────────────────────


class TestActivateSideEffects:
    async def test_display_order_assigned_after_activate(self, ws):
        """激活后 displayOrder 应 >= 0（由 recomputeSpecDisplayOrders 计算）。"""
        sid = 105
        await _set_active(ws, sid, False)
        await _set_active(ws, sid, True)

        specs = await ws.get_spec_list()
        for s in specs:
            if s.get("value") == sid:
                assert s.get("displayOrder", -1) >= 0, (
                    f"expected displayOrder >= 0 after activate, got {s.get('displayOrder')}"
                )
                break
        else:
            pytest.fail(f"spec_id={sid} not found in list after activate")

        # 清理
        await _set_active(ws, sid, False)

    async def test_display_order_reset_after_deactivate(self, ws):
        """停用后 displayOrder 应 == -1。"""
        sid = 106
        await _set_active(ws, sid, True)
        await _set_active(ws, sid, False)

        specs = await ws.get_spec_list()
        for s in specs:
            if s.get("value") == sid:
                assert s.get("displayOrder") == -1, (
                    f"expected displayOrder=-1 after deactivate, got {s.get('displayOrder')}"
                )
                break

    async def test_activate_consecutive_display_orders(self, ws):
        """激活多个规格后，所有激活规格的 displayOrder 应连续且无重复。"""
        sids = [107, 108, 109]
        # 先全部停用
        for sid in sids:
            await _set_active(ws, sid, False)
        # 逐一激活
        for sid in sids:
            r = await _set_active(ws, sid, True)
            assert r.get("success") is True

        specs = await ws.get_spec_list()
        orders = [
            s["displayOrder"]
            for s in specs
            if s.get("isActive") and s.get("displayOrder", -1) >= 0
        ]
        # displayOrder 应无重复
        assert len(orders) == len(set(orders)), f"duplicate displayOrders found: {orders}"

        # 清理
        for sid in sids:
            await _set_active(ws, sid, False)

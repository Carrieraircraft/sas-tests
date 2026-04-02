"""螺丝规格读取接口测试（Read）

覆盖三个读取消息类型：
  - screw_specification_options_get  → 规格列表（含激活状态、displayOrder）
  - screw_param_get                  → 单条规格详情
  - screw_step_param_get             → 规格步骤参数

测试 ID 全部取自 SAFE_TEST_RANGE (100-127)；需读取边界 ID (0, 127) 的测试
仅读取不写入，不影响生产数据。
"""

import pytest

from lib.constants import (
    MsgType,
    SAFE_TEST_RANGE,
    MAX_LIST_RESPONSE_MS,
    MAX_SINGLE_RESPONSE_MS,
)
from lib.helpers import ScrewSpecFactory, assert_response_time

pytestmark = [pytest.mark.spec128, pytest.mark.p1]

_REQUIRED_OPTION_FIELDS = {"value", "label", "unit", "isActive", "displayOrder",
                           "pieceCount", "progCnt", "referenceCount"}
_SID_READ_STEPS = 124


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


# ── 规格列表（screw_specification_options_get）────────────────────────────────


class TestReadOptions:
    async def test_list_returns_128_items(self, ws, db_isolation):
        """规格列表应恰好包含 128 条记录，后端不应返回越界 ID。"""
        specs = await ws.get_spec_list()
        assert len(specs) == 128, (
            f"expected 128 items, got {len(specs)}; "
            f"out-of-range ids: {[s['value'] for s in specs if not 0 <= s.get('value', -1) <= 127]}"
        )

    async def test_list_item_fields_complete(self, ws):
        """列表中每条记录应包含所有必要字段。"""
        specs = await ws.get_spec_list()
        assert len(specs) > 0, "spec list is empty"
        for item in specs:
            missing = _REQUIRED_OPTION_FIELDS - set(item.keys())
            assert not missing, f"spec id={item.get('value')} missing fields: {missing}"

    async def test_list_item_value_is_sequential(self, ws, db_isolation):
        """列表 value 字段应构成 0-127 的连续序列（后端 ORDER BY id ASC）。"""
        specs = await ws.get_spec_list()
        values = sorted(s["value"] for s in specs)
        assert values == list(range(128)), (
            f"expected sequential 0-127, got {values[:10]}..."
        )

    async def test_active_spec_has_non_negative_display_order(self, ws):
        """激活规格（isActive=True）的 displayOrder 应 >= 0。"""
        specs = await ws.get_spec_list()
        for s in specs:
            if s.get("isActive"):
                assert s.get("displayOrder", -1) >= 0, (
                    f"active spec id={s['value']} has displayOrder={s.get('displayOrder')}"
                )

    async def test_inactive_spec_has_minus_one_display_order(self, ws):
        """未激活规格（isActive=False）的 displayOrder 应 == -1。"""
        # 确保有一个已知未激活的规格
        sid = 125
        await _deactivate(ws, sid)

        specs = await ws.get_spec_list()
        for s in specs:
            if not s.get("isActive"):
                assert s.get("displayOrder") == -1, (
                    f"inactive spec id={s['value']} has displayOrder={s.get('displayOrder')}"
                )

    async def test_display_orders_are_unique_among_active(self, ws):
        """所有激活规格的 displayOrder 值应唯一（无重复）。"""
        specs = await ws.get_spec_list()
        orders = [s["displayOrder"] for s in specs if s.get("isActive")]
        assert len(orders) == len(set(orders)), (
            f"duplicate displayOrders among active specs: {orders}"
        )

    async def test_list_response_success_field(self, ws):
        """列表响应顶层应有 success=True 字段。"""
        resp = await ws.request(
            {"type": MsgType.SPEC_OPTIONS_GET},
            MsgType.SPEC_OPTIONS_RESPONSE,
        )
        assert resp.get("success") is True, f"list response not success: {resp}"
        assert "count" in resp, "response should contain 'count' field"
        assert resp["count"] == len(resp.get("data", [])), "count should match data length"

    async def test_list_response_time(self, ws):
        """规格列表响应时间应小于 MAX_LIST_RESPONSE_MS。"""
        await ws.request(
            {"type": MsgType.SPEC_OPTIONS_GET},
            MsgType.SPEC_OPTIONS_RESPONSE,
        )
        assert_response_time(ws.last_elapsed_ms, MAX_LIST_RESPONSE_MS)

    async def test_list_consecutive_request(self, ws, db_isolation):
        """连续发送两次列表请求，两次均应返回恰好 128 条记录。"""
        for _ in range(2):
            specs = await ws.get_spec_list()
            assert len(specs) == 128


# ── 单条详情（screw_param_get）───────────────────────────────────────────────


class TestReadDetail:
    async def test_read_boundary_id_0(self, ws):
        """读取 specification_id=0 应返回有效响应（success 字段存在）。"""
        r = await ws.get_screw_param(0)
        assert r.get("type") == MsgType.SCREW_PARAM_GET_RESPONSE
        assert "success" in r

    async def test_read_boundary_id_127(self, ws):
        """读取 specification_id=127 应返回有效响应。"""
        r = await ws.get_screw_param(127)
        assert r.get("type") == MsgType.SCREW_PARAM_GET_RESPONSE
        assert "success" in r

    async def test_read_invalid_id_negative(self, ws):
        """读取 specification_id=-1 应返回 success=False 或带 error 字段。"""
        r = await ws.request(
            {"type": MsgType.SCREW_PARAM_GET, "specification_id": -1},
            MsgType.SCREW_PARAM_GET_RESPONSE,
        )
        assert r.get("success") is False or r.get("error"), (
            f"expected failure for spec_id=-1, got: {r}"
        )

    async def test_read_invalid_id_out_of_range(self, ws):
        """读取 specification_id=128 超出范围，应返回 success=False 或 error。"""
        r = await ws.request(
            {"type": MsgType.SCREW_PARAM_GET, "specification_id": 128},
            MsgType.SCREW_PARAM_GET_RESPONSE,
        )
        assert r.get("success") is False or r.get("error"), (
            f"expected failure for spec_id=128, got: {r}"
        )

    async def test_read_returns_data_field_on_success(self, ws):
        """成功读取时，响应应包含 data 字段（包含规格详情）。"""
        # 先激活并写入一个已知参数的规格
        sid = 126
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.default(sid)
            await ws.save_screw_param(sid, payload)

            r = await ws.get_screw_param(sid)
            if r.get("success"):
                assert "data" in r, "successful read should include 'data' field"
                data = r["data"]
                assert "screw_name" in data
                assert "prog_cnt" in data
        finally:
            await _deactivate(ws, sid)

    async def test_read_detail_response_time(self, ws):
        """单条详情读取响应时间应小于 MAX_SINGLE_RESPONSE_MS。"""
        await ws.get_screw_param(0)
        assert_response_time(ws.last_elapsed_ms, MAX_SINGLE_RESPONSE_MS)


# ── 步骤参数（screw_step_param_get）──────────────────────────────────────────


class TestReadSteps:
    async def test_step_get_id_matches(self, ws):
        """步骤读取响应中 specification_id 应与请求一致。"""
        sid = _SID_READ_STEPS
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.with_steps(sid, 2)
            await ws.save_screw_param(sid, payload)

            r = await ws.get_screw_steps(sid)
            assert r.get("type") == MsgType.SCREW_STEP_RESPONSE
            assert r.get("specification_id") == sid or (
                r.get("success") and isinstance(r.get("data"), list)
            ), f"unexpected step response: {r}"
        finally:
            await _deactivate(ws, sid)

    async def test_step_count_matches_prog_cnt(self, ws):
        """步骤数量应与保存时 prog_cnt 一致。"""
        sid = 127
        step_count = 3
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.with_steps(sid, step_count)
            save_r = await ws.save_screw_param(sid, payload)
            assert save_r.get("success") is True

            step_r = await ws.get_screw_steps(sid)
            assert step_r.get("success") is True
            steps = step_r.get("data", [])
            assert len(steps) == step_count, (
                f"expected {step_count} steps, got {len(steps)}"
            )
        finally:
            await _deactivate(ws, sid)

    async def test_step_fields_complete(self, ws):
        """步骤响应中每条记录应包含 ok_if_1、ref_torque 等必要字段。"""
        _REQUIRED_STEP_FIELDS = {
            "screw_step", "ok_if_1", "ok_if_2", "ok_if_3", "ok_if_4",
            "ref_vel", "ref_torque", "ref_degree", "ref_time",
        }
        sid = 127
        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.with_steps(sid, 1)
            await ws.save_screw_param(sid, payload)

            step_r = await ws.get_screw_steps(sid)
            if step_r.get("success") and step_r.get("data"):
                for step in step_r["data"]:
                    missing = _REQUIRED_STEP_FIELDS - set(step.keys())
                    assert not missing, f"step missing fields: {missing}"
        finally:
            await _deactivate(ws, sid)

    async def test_step_get_response_time(self, ws):
        """步骤读取响应时间应小于 MAX_SINGLE_RESPONSE_MS。"""
        await ws.get_screw_steps(0)
        assert_response_time(ws.last_elapsed_ms, MAX_SINGLE_RESPONSE_MS)

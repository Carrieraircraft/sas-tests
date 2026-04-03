"""单螺丝模式状态机修订方案回归测试。

覆盖点（对应修订计划）：
1) 双入口配置一致性：SpecificationPage 三参数入口 / BusinessWorkModePanel 五参数入口
2) hardware_status_update 中 job_statistics 关键字段可观测
3) 单螺丝多颗模式：spec_statistics 推送、screw_cnt 影响 total_pieces、切规格后计数重置
"""

from __future__ import annotations

import asyncio
import time
import pytest

from lib.constants import MsgType
from lib.helpers import ScrewSpecFactory, ModuleFactory

pytestmark = [pytest.mark.system, pytest.mark.p0]

TEST_SCREW_ID_A = 96
TEST_SCREW_ID_B = 97
TEST_MODULE_ID_A = 96

STATUS_TIMEOUT = 8.0


async def _get_param_value(ws, param_name: str) -> str | None:
    resp = await ws.get_system_params()
    params = resp.get("data", resp)
    if isinstance(params, list):
        for p in params:
            if p.get("paramName") == param_name or p.get("param_name") == param_name:
                return p.get("paramValue") or p.get("param_value")
    if isinstance(params, dict):
        return params.get(param_name)
    return None


async def _ensure_screw_spec(ws, spec_id: int, screw_cnt: int, name: str) -> None:
    payload = ScrewSpecFactory.default(spec_id)
    payload["specification_name"] = name
    payload["detail_params"]["screw_cnt"] = screw_cnt
    resp = await ws.save_screw_param(spec_id, payload)
    assert resp.get("success") is True, f"save screw spec {spec_id} failed: {resp}"


async def _ensure_module(ws, module_id: int, screw_spec_id: int, name: str) -> None:
    payload = ModuleFactory.manual(module_id, [screw_spec_id])
    payload["product_name"] = name
    resp = await ws.save_module(module_id, payload)
    assert resp.get("success") is True or resp.get("type") == MsgType.MODULE_CONFIG_RESPONSE, (
        f"save module {module_id} failed: {resp}"
    )


async def _wait_status_after(
    ws,
    send_ts: float,
    timeout: float = STATUS_TIMEOUT,
    predicate=None,
) -> dict:
    """等待 send_ts 之后的首条满足条件的 hardware_status_update。"""
    deadline = asyncio.get_event_loop().time() + timeout
    next_idx = ws.events.count

    while asyncio.get_event_loop().time() < deadline:
        events = await ws.events.get_all()
        for ev in events[next_idx:]:
            next_idx += 1
            if ev.get("type") != MsgType.HARDWARE_STATUS_UPDATE:
                continue
            if ev.get("_received_at", 0) <= send_ts:
                continue
            if predicate is None or predicate(ev):
                return ev

        await asyncio.sleep(0.1)

    raise TimeoutError(f"No matching hardware_status_update within {timeout:.1f}s")


def _extract_job_statistics(status_msg: dict) -> dict:
    return status_msg.get("data", {}).get("job_statistics", {})


class TestDualEntryConsistency:
    async def test_specification_entry_three_params_updates_mode_and_defaults(self, ws):
        await _ensure_screw_spec(ws, TEST_SCREW_ID_A, screw_cnt=5, name="WM-Plan-Screw-A")
        await _ensure_module(ws, TEST_MODULE_ID_A, TEST_SCREW_ID_A, name="WM-Plan-Module-A")

        send_ts = time.monotonic()
        resp = await ws.request(
            {
                "type": MsgType.SYSTEM_PARAMS_BATCH_UPDATE,
                "params": [
                    {"param_name": "WorkMode", "param_value": "screw"},
                    {"param_name": "DefaultScrewId", "param_value": str(TEST_SCREW_ID_A)},
                    {"param_name": "DefaultModuleId", "param_value": str(TEST_MODULE_ID_A)},
                ],
                "modify_user": "test",
            },
            MsgType.SYSTEM_PARAMS_BATCH_UPDATE_RESPONSE,
        )
        assert resp.get("success") is True, f"3-param update failed: {resp}"

        status = await _wait_status_after(
            ws,
            send_ts,
            predicate=lambda m: _extract_job_statistics(m).get("work_mode") == "screw",
        )
        stats = _extract_job_statistics(status)
        assert stats.get("work_mode") == "screw"

        assert await _get_param_value(ws, "WorkMode") == "screw"
        assert await _get_param_value(ws, "DefaultScrewId") == str(TEST_SCREW_ID_A)
        assert await _get_param_value(ws, "DefaultModuleId") == str(TEST_MODULE_ID_A)

    async def test_business_panel_five_params_updates_mode_and_defaults(self, ws):
        await _ensure_screw_spec(ws, TEST_SCREW_ID_A, screw_cnt=5, name="WM-Plan-Screw-A")
        await _ensure_module(ws, TEST_MODULE_ID_A, TEST_SCREW_ID_A, name="WM-Plan-Module-A")

        send_ts = time.monotonic()
        resp = await ws.set_work_mode(
            "module",
            default_screw_id=TEST_SCREW_ID_A,
            default_module_id=TEST_MODULE_ID_A,
            barcode_enabled=False,
            automation_mode=False,
        )
        assert resp.get("success") is True, f"5-param update failed: {resp}"

        status = await _wait_status_after(
            ws,
            send_ts,
            predicate=lambda m: _extract_job_statistics(m).get("work_mode") == "module",
        )
        stats = _extract_job_statistics(status)
        assert stats.get("work_mode") == "module"

        assert await _get_param_value(ws, "WorkMode") == "module"
        assert await _get_param_value(ws, "DefaultScrewId") == str(TEST_SCREW_ID_A)
        assert await _get_param_value(ws, "DefaultModuleId") == str(TEST_MODULE_ID_A)


class TestSingleScrewSpecStatistics:
    async def test_status_push_contains_spec_statistics_and_matches_screw_cnt(self, ws):
        await _ensure_screw_spec(ws, TEST_SCREW_ID_A, screw_cnt=5, name="WM-Plan-Screw-A-5")

        send_ts = time.monotonic()
        resp = await ws.set_work_mode(
            "screw",
            default_screw_id=TEST_SCREW_ID_A,
            default_module_id=TEST_MODULE_ID_A,
            barcode_enabled=False,
            automation_mode=False,
        )
        assert resp.get("success") is True, f"set work mode failed: {resp}"

        status = await _wait_status_after(
            ws,
            send_ts,
            predicate=lambda m: "job_statistics" in m.get("data", {}),
        )
        stats = _extract_job_statistics(status)

        assert stats.get("work_mode") == "screw", f"unexpected stats: {stats}"
        assert stats.get("current_screw_name") == "WM-Plan-Screw-A-5", f"unexpected stats: {stats}"

        spec_stats = stats.get("spec_statistics")
        assert isinstance(spec_stats, dict), f"spec_statistics missing in job_statistics: {stats}"
        assert spec_stats.get("spec_total_count") == 5, f"spec_total_count should be 5: {spec_stats}"
        assert spec_stats.get("total_pieces") == 5, f"total_pieces should be 5: {spec_stats}"
        assert 1 <= int(spec_stats.get("current_piece", 0)) <= 5, f"current_piece out of range: {spec_stats}"

    async def test_switch_default_screw_resets_piece_progress_and_total(self, ws):
        await _ensure_screw_spec(ws, TEST_SCREW_ID_A, screw_cnt=5, name="WM-Plan-Screw-A-5")
        await _ensure_screw_spec(ws, TEST_SCREW_ID_B, screw_cnt=2, name="WM-Plan-Screw-B-2")

        send_ts_a = time.monotonic()
        resp_a = await ws.set_work_mode(
            "screw",
            default_screw_id=TEST_SCREW_ID_A,
            default_module_id=TEST_MODULE_ID_A,
            barcode_enabled=False,
            automation_mode=False,
        )
        assert resp_a.get("success") is True
        status_a = await _wait_status_after(
            ws,
            send_ts_a,
            predicate=lambda m: _extract_job_statistics(m).get("current_screw_name") == "WM-Plan-Screw-A-5",
        )
        stats_a = _extract_job_statistics(status_a)
        spec_a = stats_a.get("spec_statistics", {})
        assert spec_a.get("total_pieces") == 5, f"unexpected spec A stats: {spec_a}"

        send_ts_b = time.monotonic()
        resp_b = await ws.set_work_mode(
            "screw",
            default_screw_id=TEST_SCREW_ID_B,
            default_module_id=TEST_MODULE_ID_A,
            barcode_enabled=False,
            automation_mode=False,
        )
        assert resp_b.get("success") is True
        status_b = await _wait_status_after(
            ws,
            send_ts_b,
            predicate=lambda m: _extract_job_statistics(m).get("current_screw_name") == "WM-Plan-Screw-B-2",
        )
        stats_b = _extract_job_statistics(status_b)
        spec_b = stats_b.get("spec_statistics", {})

        assert stats_b.get("work_mode") == "screw", f"unexpected stats B: {stats_b}"
        assert spec_b.get("total_pieces") == 2, f"switch to screw B should update total to 2: {spec_b}"
        assert spec_b.get("spec_total_count") == 2, f"switch to screw B should update spec_total_count: {spec_b}"
        assert spec_b.get("current_piece") == 1, f"switch spec should reset current_piece to 1: {spec_b}"


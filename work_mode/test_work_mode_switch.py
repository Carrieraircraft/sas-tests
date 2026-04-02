"""业务工作模式切换测试

验证从螺丝模式切换到模组模式（及反向切换）后，后端状态机能正确响应，
hardware_status_update 推送中 work_mode 字段能反映最新配置。

等待策略说明：
  系统在非条码模式下，IDLE onEnter 加载完参数后立刻进入 JOB_PREPARE → READY_STANDBY，
  hardware_status_update 是 MCU 状态轮询驱动的周期推送，切换完成后下一条推送携带新值。

  _recv_loop 是独立 asyncio task，clear() 与 wait 之间存在竞争窗口：clear() 之后、
  send 命令之前，_recv_loop 可能已将旧推送压入 accumulator。
  正确做法：记录 send 前的 time.monotonic() 时间戳，只接受 _received_at > send_ts 的推送。
"""

import asyncio
import time
import pytest

from lib.constants import MsgType
from lib.helpers import ScrewSpecFactory, ModuleFactory

pytestmark = [pytest.mark.system, pytest.mark.p1]

TEST_SCREW_ID_A = 110
TEST_SCREW_ID_B = 111
TEST_MODULE_ID_A = 110
TEST_MODULE_ID_B = 111

# 300ms防抖 + 状态机处理 + 至少一次推送周期（推送约1s一次）
STATUS_WAIT_TIMEOUT = 6.0


# ── 辅助 ─────────────────────────────────────────────────────────────────────


async def _wait_work_mode_after(ws, send_ts: float, expected: str, timeout: float = STATUS_WAIT_TIMEOUT) -> str:
    """只消费 send_ts 之后收到的 hardware_status_update，直到 work_mode == expected 或超时。

    关键：用全量事件列表的索引游标推进，避免 wait_for_event 从头重扫同一条消息。
    每次从游标往后扫，处理完的位置向前移，绝不回头。
    """
    deadline = asyncio.get_event_loop().time() + timeout
    last_mode: str | None = None
    # 先取当前全量积累长度作为起始游标，只处理从此刻开始的新消息
    next_idx = ws.events.count

    while asyncio.get_event_loop().time() < deadline:
        # 读取全量事件（不过滤类型，保持索引连续）
        all_events = await ws.events.get_all()
        for ev in all_events[next_idx:]:
            next_idx += 1
            if ev.get("type") != MsgType.HARDWARE_STATUS_UPDATE:
                continue
            if ev.get("_received_at", 0) <= send_ts:
                continue
            stats = ev.get("data", {}).get("job_statistics", {})
            if "work_mode" not in stats:
                continue
            last_mode = stats["work_mode"]
            if last_mode == expected:
                return last_mode
            # 命令后的新推送但值还不对，继续等下一条

        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            break
        await asyncio.sleep(min(0.1, remaining))

    return last_mode or ""


async def _switch_and_wait(ws, work_mode: str, expected: str, timeout: float = STATUS_WAIT_TIMEOUT, **kwargs) -> str:
    """记录时间戳 → 发命令 → 只等该时间戳之后的推送。
    send_ts 在发命令前记录，_wait_work_mode_after 内部用游标确保不回头扫旧消息。
    """
    send_ts = time.monotonic()
    resp = await ws.set_work_mode(work_mode, **kwargs)
    assert resp.get("success") is True, f"切换 {work_mode} 模式失败: {resp}"
    return await _wait_work_mode_after(ws, send_ts, expected, timeout)


async def _get_param_value(ws, param_name: str) -> str | None:
    """从 system_params 数据响应中读取指定参数值。"""
    resp = await ws.get_system_params()
    params = resp.get("data", resp)
    if isinstance(params, list):
        for p in params:
            if p.get("paramName") == param_name or p.get("param_name") == param_name:
                return p.get("paramValue") or p.get("param_value")
    elif isinstance(params, dict):
        return params.get(param_name)
    return None


async def _ensure_screw_spec(ws, spec_id: int) -> None:
    payload = ScrewSpecFactory.default(spec_id)
    payload["specification_name"] = f"WM-Test-Screw-{spec_id}"
    resp = await ws.save_screw_param(spec_id, payload)
    assert resp.get("success") is True, f"创建螺丝规格 {spec_id} 失败: {resp}"


async def _ensure_module(ws, module_id: int, screw_spec_id: int) -> None:
    payload = ModuleFactory.manual(module_id, [screw_spec_id])
    payload["product_name"] = f"WM-Test-Module-{module_id}"
    resp = await ws.save_module(module_id, payload)
    assert resp.get("success") is True or resp.get("type") == MsgType.MODULE_CONFIG_RESPONSE, \
        f"创建模组 {module_id} 失败: {resp}"


# ── 测试类 ────────────────────────────────────────────────────────────────────


class TestWorkModeSwitchBasic:
    """基础工作模式切换：单次切换后验证推送和DB"""

    async def test_switch_to_screw_mode(self, ws):
        """切换到螺丝模式后，hardware_status_update 中 work_mode 应为 'screw'"""
        await _ensure_screw_spec(ws, TEST_SCREW_ID_A)

        actual_mode = await _switch_and_wait(
            ws, "screw", "screw",
            default_screw_id=TEST_SCREW_ID_A,
            default_module_id=TEST_MODULE_ID_A,
        )
        assert actual_mode == "screw", (
            f"切换螺丝模式后推送中 work_mode = '{actual_mode}'，期望 'screw'。"
            "可能原因：防抖回调未触发，或状态机未更新 StateContext 中的 work_mode。"
        )

    async def test_switch_to_module_mode(self, ws):
        """切换到模组模式后，hardware_status_update 中 work_mode 应为 'module'"""
        await _ensure_screw_spec(ws, TEST_SCREW_ID_A)
        await _ensure_module(ws, TEST_MODULE_ID_A, TEST_SCREW_ID_A)

        actual_mode = await _switch_and_wait(
            ws, "module", "module",
            default_screw_id=TEST_SCREW_ID_A,
            default_module_id=TEST_MODULE_ID_A,
        )
        assert actual_mode == "module", (
            f"切换模组模式后推送中 work_mode = '{actual_mode}'，期望 'module'。"
            "可能原因：SE_CONFIG_REFRESHED 中模组参数加载失败，或 work_mode 未写入 StateContext。"
        )

    async def test_db_persisted_after_switch_to_screw(self, ws):
        """切换到螺丝模式后，系统参数 WorkMode 应在 DB 中持久化为 'screw'"""
        resp = await ws.set_work_mode("screw", default_screw_id=TEST_SCREW_ID_A)
        assert resp.get("success") is True
        await asyncio.sleep(0.5)

        value = await _get_param_value(ws, "WorkMode")
        assert value == "screw", f"DB 中 WorkMode = '{value}'，期望 'screw'"

    async def test_db_persisted_after_switch_to_module(self, ws):
        """切换到模组模式后，系统参数 WorkMode 应在 DB 中持久化为 'module'"""
        await _ensure_module(ws, TEST_MODULE_ID_A, TEST_SCREW_ID_A)
        resp = await ws.set_work_mode("module", default_module_id=TEST_MODULE_ID_A)
        assert resp.get("success") is True
        await asyncio.sleep(0.5)

        value = await _get_param_value(ws, "WorkMode")
        assert value == "module", f"DB 中 WorkMode = '{value}'，期望 'module'"


class TestWorkModeSwitchWithDifferentSpecs:
    """切换工作模式时使用不同的螺丝规格/模组规格"""

    async def test_screw_mode_with_spec_a(self, ws):
        """螺丝模式 + 规格A：推送中应携带 work_mode = 'screw'，DefaultScrewId 匹配"""
        await _ensure_screw_spec(ws, TEST_SCREW_ID_A)

        actual_mode = await _switch_and_wait(ws, "screw", "screw", default_screw_id=TEST_SCREW_ID_A)
        assert actual_mode == "screw", f"规格A螺丝模式推送 work_mode = '{actual_mode}'"

        screw_id_val = await _get_param_value(ws, "DefaultScrewId")
        assert screw_id_val == str(TEST_SCREW_ID_A), (
            f"DefaultScrewId = '{screw_id_val}'，期望 '{TEST_SCREW_ID_A}'"
        )

    async def test_screw_mode_with_spec_b(self, ws):
        """螺丝模式 + 规格B"""
        await _ensure_screw_spec(ws, TEST_SCREW_ID_B)

        actual_mode = await _switch_and_wait(ws, "screw", "screw", default_screw_id=TEST_SCREW_ID_B)
        assert actual_mode == "screw"

        screw_id_val = await _get_param_value(ws, "DefaultScrewId")
        assert screw_id_val == str(TEST_SCREW_ID_B)

    async def test_module_mode_with_module_a(self, ws):
        """模组模式 + 模组A"""
        await _ensure_screw_spec(ws, TEST_SCREW_ID_A)
        await _ensure_module(ws, TEST_MODULE_ID_A, TEST_SCREW_ID_A)

        actual_mode = await _switch_and_wait(ws, "module", "module", default_module_id=TEST_MODULE_ID_A)
        assert actual_mode == "module"

        module_id_val = await _get_param_value(ws, "DefaultModuleId")
        assert module_id_val == str(TEST_MODULE_ID_A)

    async def test_module_mode_with_module_b(self, ws):
        """模组模式 + 模组B"""
        await _ensure_screw_spec(ws, TEST_SCREW_ID_B)
        await _ensure_module(ws, TEST_MODULE_ID_B, TEST_SCREW_ID_B)

        actual_mode = await _switch_and_wait(ws, "module", "module", default_module_id=TEST_MODULE_ID_B)
        assert actual_mode == "module"

        module_id_val = await _get_param_value(ws, "DefaultModuleId")
        assert module_id_val == str(TEST_MODULE_ID_B)


class TestWorkModeSwitchRoundTrip:
    """来回切换测试：多次螺丝↔模组切换"""

    async def test_screw_then_module(self, ws):
        """螺丝模式 → 模组模式"""
        await _ensure_screw_spec(ws, TEST_SCREW_ID_A)
        await _ensure_module(ws, TEST_MODULE_ID_A, TEST_SCREW_ID_A)

        mode1 = await _switch_and_wait(ws, "screw", "screw",
                                       default_screw_id=TEST_SCREW_ID_A,
                                       default_module_id=TEST_MODULE_ID_A)
        assert mode1 == "screw", f"第1次切换(螺丝)后 work_mode = '{mode1}'"

        mode2 = await _switch_and_wait(ws, "module", "module",
                                       default_screw_id=TEST_SCREW_ID_A,
                                       default_module_id=TEST_MODULE_ID_A)
        assert mode2 == "module", f"第2次切换(模组)后 work_mode = '{mode2}'"

    async def test_module_then_screw(self, ws):
        """模组模式 → 螺丝模式"""
        await _ensure_screw_spec(ws, TEST_SCREW_ID_A)
        await _ensure_module(ws, TEST_MODULE_ID_A, TEST_SCREW_ID_A)

        mode1 = await _switch_and_wait(ws, "module", "module",
                                       default_screw_id=TEST_SCREW_ID_A,
                                       default_module_id=TEST_MODULE_ID_A)
        assert mode1 == "module", f"第1次切换(模组)后 work_mode = '{mode1}'"

        mode2 = await _switch_and_wait(ws, "screw", "screw",
                                       default_screw_id=TEST_SCREW_ID_A,
                                       default_module_id=TEST_MODULE_ID_A)
        assert mode2 == "screw", f"第2次切换(螺丝)后 work_mode = '{mode2}'"

    async def test_multiple_round_trips(self, ws):
        """连续6次来回切换，每次都应该正确响应"""
        await _ensure_screw_spec(ws, TEST_SCREW_ID_A)
        await _ensure_module(ws, TEST_MODULE_ID_A, TEST_SCREW_ID_A)

        sequence = [
            ("screw", TEST_SCREW_ID_A, TEST_MODULE_ID_A),
            ("module", TEST_SCREW_ID_A, TEST_MODULE_ID_A),
            ("screw", TEST_SCREW_ID_A, TEST_MODULE_ID_A),
            ("module", TEST_SCREW_ID_A, TEST_MODULE_ID_A),
            ("screw", TEST_SCREW_ID_A, TEST_MODULE_ID_A),
            ("module", TEST_SCREW_ID_A, TEST_MODULE_ID_A),
        ]

        for i, (mode, screw_id, module_id) in enumerate(sequence):
            actual = await _switch_and_wait(ws, mode, mode,
                                            default_screw_id=screw_id,
                                            default_module_id=module_id)
            assert actual == mode, (
                f"第{i+1}次切换({mode})后推送 work_mode = '{actual}'，期望 '{mode}'"
            )

    async def test_switch_spec_within_screw_mode(self, ws):
        """螺丝模式内切换不同规格（DefaultScrewId）"""
        await _ensure_screw_spec(ws, TEST_SCREW_ID_A)
        await _ensure_screw_spec(ws, TEST_SCREW_ID_B)

        await _switch_and_wait(ws, "screw", "screw", default_screw_id=TEST_SCREW_ID_A)

        actual_mode = await _switch_and_wait(ws, "screw", "screw", default_screw_id=TEST_SCREW_ID_B)
        assert actual_mode == "screw"

        screw_id_val = await _get_param_value(ws, "DefaultScrewId")
        assert screw_id_val == str(TEST_SCREW_ID_B), (
            f"DefaultScrewId = '{screw_id_val}'，期望 '{TEST_SCREW_ID_B}'"
        )

    async def test_switch_module_within_module_mode(self, ws):
        """模组模式内切换不同模组（DefaultModuleId）"""
        await _ensure_screw_spec(ws, TEST_SCREW_ID_A)
        await _ensure_screw_spec(ws, TEST_SCREW_ID_B)
        await _ensure_module(ws, TEST_MODULE_ID_A, TEST_SCREW_ID_A)
        await _ensure_module(ws, TEST_MODULE_ID_B, TEST_SCREW_ID_B)

        await _switch_and_wait(ws, "module", "module", default_module_id=TEST_MODULE_ID_A)

        actual_mode = await _switch_and_wait(ws, "module", "module", default_module_id=TEST_MODULE_ID_B)
        assert actual_mode == "module"

        module_id_val = await _get_param_value(ws, "DefaultModuleId")
        assert module_id_val == str(TEST_MODULE_ID_B), (
            f"DefaultModuleId = '{module_id_val}'，期望 '{TEST_MODULE_ID_B}'"
        )


class TestWorkModeSwitchMinimalParams:
    """使用规格页面的三参数批量更新（不含 BarcodeEnabled / AutomationMode）"""

    async def _minimal_switch_and_wait(self, ws, work_mode: str, screw_id: int, module_id: int) -> str:
        """模拟 SpecificationPage 三参数批量更新，用时间戳隔离旧推送后等待新推送。"""
        send_ts = time.monotonic()
        msg = {
            "type": MsgType.SYSTEM_PARAMS_BATCH_UPDATE,
            "params": [
                {"param_name": "WorkMode", "param_value": work_mode},
                {"param_name": "DefaultScrewId", "param_value": str(screw_id)},
                {"param_name": "DefaultModuleId", "param_value": str(module_id)},
            ],
            "modify_user": "test",
        }
        resp = await ws.request(msg, MsgType.SYSTEM_PARAMS_BATCH_UPDATE_RESPONSE)
        assert resp.get("success") is True, f"三参数切换 {work_mode} 模式失败: {resp}"
        return await _wait_work_mode_after(ws, send_ts, work_mode)

    async def test_minimal_switch_to_screw(self, ws):
        """三参数批量更新切换到螺丝模式"""
        await _ensure_screw_spec(ws, TEST_SCREW_ID_A)

        actual_mode = await self._minimal_switch_and_wait(ws, "screw", TEST_SCREW_ID_A, TEST_MODULE_ID_A)
        assert actual_mode == "screw", (
            f"三参数批量更新后推送 work_mode = '{actual_mode}'，期望 'screw'"
        )

    async def test_minimal_switch_to_module(self, ws):
        """三参数批量更新切换到模组模式"""
        await _ensure_screw_spec(ws, TEST_SCREW_ID_A)
        await _ensure_module(ws, TEST_MODULE_ID_A, TEST_SCREW_ID_A)

        actual_mode = await self._minimal_switch_and_wait(ws, "module", TEST_SCREW_ID_A, TEST_MODULE_ID_A)
        assert actual_mode == "module", (
            f"三参数批量更新后推送 work_mode = '{actual_mode}'，期望 'module'"
        )


class TestWorkModeSwitchEdgeCases:
    """边界与异常场景"""

    async def test_single_param_update_workmode(self, ws):
        """使用单参数 system_param_update 更新 WorkMode，也应触发状态机响应"""
        await _ensure_screw_spec(ws, TEST_SCREW_ID_A)

        send_ts = time.monotonic()
        resp = await ws.request(
            {
                "type": MsgType.SYSTEM_PARAM_UPDATE,
                "param_name": "WorkMode",
                "param_value": "screw",
                "modify_user": "test",
            },
            MsgType.SYSTEM_PARAM_UPDATE_RESPONSE,
        )
        assert resp.get("success") is True, f"单参数更新 WorkMode 失败: {resp}"

        actual_mode = await _wait_work_mode_after(ws, send_ts, "screw")
        assert actual_mode == "screw", (
            f"单参数更新 WorkMode 后推送 work_mode = '{actual_mode}'，期望 'screw'"
        )

    async def test_repeated_same_mode_switch(self, ws):
        """多次发送相同的模式（螺丝→螺丝），应正常处理不报错"""
        await _ensure_screw_spec(ws, TEST_SCREW_ID_A)

        for i in range(3):
            actual_mode = await _switch_and_wait(ws, "screw", "screw",
                                                 default_screw_id=TEST_SCREW_ID_A)
            assert actual_mode == "screw", f"第{i+1}次重复切换后 work_mode = '{actual_mode}'"

    async def test_debounce_rapid_switch(self, ws):
        """快速连续切换（在防抖窗口内），最终状态应以最后一条为准（最后发送 module）"""
        await _ensure_screw_spec(ws, TEST_SCREW_ID_A)
        await _ensure_module(ws, TEST_MODULE_ID_A, TEST_SCREW_ID_A)

        msg_module = {
            "type": MsgType.SYSTEM_PARAMS_BATCH_UPDATE,
            "params": [
                {"param_name": "BarcodeEnabled", "param_value": "false"},
                {"param_name": "WorkMode", "param_value": "module"},
                {"param_name": "AutomationMode", "param_value": "false"},
                {"param_name": "DefaultScrewId", "param_value": str(TEST_SCREW_ID_A)},
                {"param_name": "DefaultModuleId", "param_value": str(TEST_MODULE_ID_A)},
            ],
            "modify_user": "test",
        }
        msg_screw = {
            "type": MsgType.SYSTEM_PARAMS_BATCH_UPDATE,
            "params": [
                {"param_name": "BarcodeEnabled", "param_value": "false"},
                {"param_name": "WorkMode", "param_value": "screw"},
                {"param_name": "AutomationMode", "param_value": "false"},
                {"param_name": "DefaultScrewId", "param_value": str(TEST_SCREW_ID_A)},
                {"param_name": "DefaultModuleId", "param_value": str(TEST_MODULE_ID_A)},
            ],
            "modify_user": "test",
        }

        send_ts = time.monotonic()
        # 快速连发三条（200ms 内，在防抖窗口 300ms 之内），最后一条是 module
        await ws.send(msg_module)
        await asyncio.sleep(0.05)
        await ws.send(msg_screw)
        await asyncio.sleep(0.05)
        await ws.send(msg_module)

        for _ in range(3):
            try:
                await ws.wait_for(MsgType.SYSTEM_PARAMS_BATCH_UPDATE_RESPONSE, timeout=3.0)
            except TimeoutError:
                break

        actual_mode = await _wait_work_mode_after(ws, send_ts, "module", timeout=STATUS_WAIT_TIMEOUT)
        assert actual_mode == "module", (
            f"快速切换后最终 work_mode = '{actual_mode}'，期望 'module'（最后一条为模组模式）"
        )

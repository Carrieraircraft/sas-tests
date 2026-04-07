"""螺丝参数写入 DB + MCU 双重验证测试

验证链：
    screw_param_config (WebSocket)
        → 数据库 (Mode1_Screw_Param / Mode1_Steps_Param)
        → MCU SPI flash (CONFIG_DATA.ctrl_cfg.screw_cfg.screw[slot])

运行要求：
    - --ssh-host=192.168.0.221   (树莓派 IP)
    - --ssh-user=pi              (SSH 用户，默认 pi)
    - --ssh-password=<pwd>       或 --ssh-key=<path>
    - 树莓派上 pi 用户有 sudo 权限（MCU dump 需要 root 访问 SPI）
    - 树莓派上存在 dump_mcu_config.py（路径见 RemoteBackend.DUMP_MCU_SCRIPT）

运行示例：
    cd e:\\SoftDev\\SAS_Dev\\tests
    python -m pytest spec128/test_screw_mcu_verify.py -v \\
        --ssh-host=192.168.0.221 --ssh-user=pi --ssh-password=xxx

带 MCU 验证（需 sudo + 真实 MCU）：
    python -m pytest spec128/test_screw_mcu_verify.py -v -m hardware \\
        --ssh-host=192.168.0.221 --ssh-password=xxx

注意：
    MCU 物理槽位（0-15）与逻辑 ID（0-127）的映射由后端 SlotTable 管理。
    只有被激活并写入 SlotTable 的逻辑 ID 才会同步到 MCU 对应物理槽位。
    测试通过 slot_status_get WebSocket 消息或直接 SSH 查询 DB 来获取映射。
"""

import os
import tempfile

import pytest

from lib.constants import MsgType, SAFE_TEST_RANGE
from lib.helpers import ScrewSpecFactory
from lib.mcu_verifier import McuVerifier

pytestmark = [pytest.mark.spec128, pytest.mark.p2]

# 专用测试 ID（避免与其他 spec128 测试冲突）
_SID_DB_VERIFY  = 115   # DB 验证专用
_SID_MCU_VERIFY = 116   # MCU 验证专用（需要硬件）

# MCU 物理槽位数（0-15）
_MCU_SLOT_COUNT = 16


# ── 辅助函数 ──────────────────────────────────────────────────────────────────


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


async def _get_slot_for_spec(ws, spec_id: int) -> int | None:
    """通过 slot_status_get 查询逻辑 ID 对应的 MCU 物理槽位（0-15）。
    
    返回 None 表示该逻辑 ID 未映射到任何物理槽位（未被 SlotTable 分配）。
    """
    try:
        resp = await ws.request(
            {"type": MsgType.SLOT_STATUS_GET},
            MsgType.SLOT_STATUS_RESPONSE,
        )
        slots = resp.get("data", [])
        for entry in slots:
            if entry.get("spec_id") == spec_id or entry.get("logical_id") == spec_id:
                return entry.get("slot") if "slot" in entry else entry.get("physical_slot")
        return None
    except (TimeoutError, KeyError):
        return None


# ── DB 验证测试（只需 SSH，不需要 MCU dump）────────────────────────────────────


class TestDbVerify:
    """通过 SSH 直接查询 SQLite 数据库，验证 WS 写入后数据库记录正确。
    
    这组测试需要 --ssh-host，但不需要真实 MCU。
    """

    async def test_save_writes_screw_name_to_db(self, ws, remote):
        """保存规格名称后，数据库中对应行的 screw_name 应与发送值一致。"""
        sid = _SID_DB_VERIFY
        name = f"DbVerify-{sid}"

        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.default(sid)
            payload["specification_name"] = name
            resp = await ws.save_screw_param(sid, payload)
            assert resp.get("success") is True, f"save failed: {resp}"

            rows = await remote.query_db(
                f"SELECT screw_name FROM Mode1_Screw_Param WHERE id={sid}"
            )
            assert rows, f"No DB row found for id={sid}"
            assert rows[0]["screw_name"] == name, (
                f"DB screw_name mismatch: expected '{name}', got '{rows[0]['screw_name']}'"
            )
        finally:
            await _deactivate(ws, sid)

    async def test_save_writes_prog_cnt_to_db(self, ws, remote):
        """保存 prog_cnt=3 后，数据库中对应行的 prog_cnt 应等于 3。"""
        sid = _SID_DB_VERIFY
        step_count = 3

        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.with_steps(sid, step_count)
            resp = await ws.save_screw_param(sid, payload)
            assert resp.get("success") is True, f"save failed: {resp}"

            rows = await remote.query_db(
                f"SELECT prog_cnt, is_active FROM Mode1_Screw_Param WHERE id={sid}"
            )
            assert rows, f"No DB row found for id={sid}"
            assert rows[0]["prog_cnt"] == step_count, (
                f"DB prog_cnt mismatch: expected {step_count}, got {rows[0]['prog_cnt']}"
            )
        finally:
            await _deactivate(ws, sid)

    async def test_save_sets_is_active_in_db(self, ws, remote):
        """通过 screw_param_config 保存参数后，DB 中 is_active 应自动变为 1
        （验证 ensureSpecActive 逻辑）。"""
        sid = _SID_DB_VERIFY

        # 先停用确保初始状态为未激活
        await _deactivate(ws, sid)

        # 直接保存（不先激活）
        payload = ScrewSpecFactory.default(sid)
        resp = await ws.save_screw_param(sid, payload)
        assert resp.get("success") is True, f"save failed: {resp}"

        try:
            rows = await remote.query_db(
                f"SELECT is_active FROM Mode1_Screw_Param WHERE id={sid}"
            )
            assert rows, f"No DB row found for id={sid}"
            assert rows[0]["is_active"] == 1, (
                f"Expected is_active=1 after save (ensureSpecActive), "
                f"got {rows[0]['is_active']}"
            )
        finally:
            await _deactivate(ws, sid)

    async def test_save_writes_steps_to_db(self, ws, remote):
        """保存 2 个步骤后，Mode1_Steps_Param 中应有 2 条 screw_id={sid} 的记录。"""
        sid = _SID_DB_VERIFY
        step_count = 2

        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.with_steps(sid, step_count)
            resp = await ws.save_screw_param(sid, payload)
            assert resp.get("success") is True, f"save failed: {resp}"

            rows = await remote.query_db(
                f"SELECT screw_step, ref_torque FROM Mode1_Steps_Param "
                f"WHERE screw_id={sid} ORDER BY screw_step"
            )
            assert len(rows) == step_count, (
                f"Expected {step_count} step rows in DB for id={sid}, "
                f"got {len(rows)}: {rows}"
            )
        finally:
            await _deactivate(ws, sid)

    async def test_deactivate_clears_is_active_in_db(self, ws, remote):
        """停用规格后，DB 中 is_active 应变为 0。"""
        sid = _SID_DB_VERIFY

        # 先激活并保存
        await _activate(ws, sid)
        await ws.save_screw_param(sid, ScrewSpecFactory.default(sid))

        # 停用
        await _deactivate(ws, sid)

        rows = await remote.query_db(
            f"SELECT is_active FROM Mode1_Screw_Param WHERE id={sid}"
        )
        assert rows, f"No DB row found for id={sid}"
        assert rows[0]["is_active"] == 0, (
            f"Expected is_active=0 after deactivate, got {rows[0]['is_active']}"
        )

    async def test_clone_copies_data_in_db(self, ws, remote):
        """克隆后，目标规格的 DB 记录与源规格一致（名称带 ' (副本)' 后缀）。"""
        src, tgt = 120, 121
        name = f"CloneSrc-{src}"

        await _activate(ws, src)
        payload = ScrewSpecFactory.default(src)
        payload["specification_name"] = name
        await ws.save_screw_param(src, payload)

        try:
            clone_r = await ws.clone_screw_spec(src, tgt)
            assert clone_r.get("success") is True, f"clone failed: {clone_r}"

            rows = await remote.query_db(
                f"SELECT screw_name, prog_cnt FROM Mode1_Screw_Param WHERE id={tgt}"
            )
            assert rows, f"No DB row found for cloned target id={tgt}"
            assert name in rows[0]["screw_name"] or rows[0]["screw_name"].endswith("(副本)"), (
                f"Cloned name unexpected: {rows[0]['screw_name']}"
            )
        finally:
            await _deactivate(ws, src)
            await _deactivate(ws, tgt)


# ── MCU 验证测试（需要 sudo + 真实 MCU + SPI）────────────────────────────────


@pytest.mark.hardware
class TestMcuWriteVerify:
    """通过 SSH 执行 dump_mcu_config.py，下载 .bin 并本地解析，验证 MCU 内存参数。
    
    这组测试需要：
        1. --ssh-host 指向树莓派
        2. pi 用户有 sudo 权限
        3. 树莓派上有 DUMP_MCU_SCRIPT（dump_mcu_config.py）
        4. 真实 MCU 已连接（SPI 通信）
    
    标记 @pytest.mark.hardware 表示需要真实硬件，可用 -m "not hardware" 跳过。
    """

    async def test_prog_cnt_in_mcu(self, ws, remote):
        """保存 prog_cnt=3 后，MCU 对应物理槽位的 prog_cnt 应等于 3。"""
        sid = _SID_MCU_VERIFY
        step_count = 3

        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.with_steps(sid, step_count)
            resp = await ws.save_screw_param(sid, payload)
            assert resp.get("success") is True, f"save failed: {resp}"

            # 获取逻辑 ID 对应的物理槽位
            slot = await _get_slot_for_spec(ws, sid)
            if slot is None:
                pytest.skip(
                    f"spec_id={sid} is not mapped to any MCU physical slot "
                    f"(SlotTable may be full or spec not in active 0-15 range)"
                )

            # SSH dump MCU
            with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
                local_bin = tmp.name

            try:
                remote_bin = await remote.dump_mcu_to_bin()
                await remote.download_mcu_bin(remote_bin, local_bin)

                verifier = McuVerifier(local_bin)
                got = verifier.get_prog_cnt(slot)
                assert got == step_count, (
                    f"MCU slot={slot} prog_cnt={got}, expected {step_count}"
                )
            finally:
                if os.path.exists(local_bin):
                    os.unlink(local_bin)
        finally:
            await _deactivate(ws, sid)

    async def test_ref_torque_in_mcu(self, ws, remote):
        """保存步骤 ref_torque=0.55 后，MCU 对应 prog[0].ref_torque 应接近 0.55。"""
        sid = _SID_MCU_VERIFY
        ref_torque = 0.55

        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.with_steps(sid, 1)
            payload["detail_params"]["torque_min"] = 0.1
            payload["detail_params"]["torque_target"] = 0.5
            payload["detail_params"]["torque_max"] = 0.6
            payload["step_params"][0]["ref_torque"] = ref_torque
            resp = await ws.save_screw_param(sid, payload)
            assert resp.get("success") is True, f"save failed: {resp}"

            slot = await _get_slot_for_spec(ws, sid)
            if slot is None:
                pytest.skip(f"spec_id={sid} not mapped to MCU slot")

            with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
                local_bin = tmp.name

            try:
                remote_bin = await remote.dump_mcu_to_bin()
                await remote.download_mcu_bin(remote_bin, local_bin)

                verifier = McuVerifier(local_bin)
                got = verifier.get_ref_torque(slot, step=0)
                assert abs(got - ref_torque) < 0.01, (
                    f"MCU slot={slot} prog[0].ref_torque={got:.4f}, "
                    f"expected ≈{ref_torque}"
                )
            finally:
                if os.path.exists(local_bin):
                    os.unlink(local_bin)
        finally:
            await _deactivate(ws, sid)

    async def test_screw_name_in_mcu(self, ws, remote):
        """保存 specification_name 后，MCU 对应槽位的 screw_name 应包含该名称。"""
        sid = _SID_MCU_VERIFY
        name = f"McuTest-{sid}"

        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.default(sid)
            payload["specification_name"] = name
            resp = await ws.save_screw_param(sid, payload)
            assert resp.get("success") is True, f"save failed: {resp}"

            slot = await _get_slot_for_spec(ws, sid)
            if slot is None:
                pytest.skip(f"spec_id={sid} not mapped to MCU slot")

            with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
                local_bin = tmp.name

            try:
                remote_bin = await remote.dump_mcu_to_bin()
                await remote.download_mcu_bin(remote_bin, local_bin)

                verifier = McuVerifier(local_bin)
                got_name = verifier.get_screw_name(slot)
                assert name in got_name or got_name == name, (
                    f"MCU slot={slot} screw_name='{got_name}', expected to contain '{name}'"
                )
            finally:
                if os.path.exists(local_bin):
                    os.unlink(local_bin)
        finally:
            await _deactivate(ws, sid)

    async def test_db_and_mcu_consistent(self, ws, remote):
        """双重验证：数据库记录与 MCU 内存中的 prog_cnt 和 screw_name 应完全一致。"""
        sid = _SID_MCU_VERIFY
        step_count = 2
        name = f"DualVerify-{sid}"

        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.with_steps(sid, step_count)
            payload["specification_name"] = name
            resp = await ws.save_screw_param(sid, payload)
            assert resp.get("success") is True, f"save failed: {resp}"

            slot = await _get_slot_for_spec(ws, sid)
            if slot is None:
                pytest.skip(f"spec_id={sid} not mapped to MCU slot")

            # — DB 验证 —
            rows = await remote.query_db(
                f"SELECT screw_name, prog_cnt, is_active "
                f"FROM Mode1_Screw_Param WHERE id={sid}"
            )
            assert rows, f"No DB row for id={sid}"
            db_name    = rows[0]["screw_name"]
            db_prog_cnt = rows[0]["prog_cnt"]
            assert rows[0]["is_active"] == 1, "spec should be active in DB"
            assert db_prog_cnt == step_count, (
                f"DB prog_cnt={db_prog_cnt}, expected {step_count}"
            )
            assert db_name == name, f"DB name='{db_name}', expected '{name}'"

            # — MCU 验证 —
            with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
                local_bin = tmp.name

            try:
                remote_bin = await remote.dump_mcu_to_bin()
                await remote.download_mcu_bin(remote_bin, local_bin)

                verifier = McuVerifier(local_bin)
                mcu_prog_cnt = verifier.get_prog_cnt(slot)
                mcu_name     = verifier.get_screw_name(slot)

                assert mcu_prog_cnt == db_prog_cnt, (
                    f"MCU prog_cnt={mcu_prog_cnt} != DB prog_cnt={db_prog_cnt} "
                    f"(slot={slot}, spec_id={sid})"
                )
                assert mcu_name == db_name or db_name in mcu_name, (
                    f"MCU name='{mcu_name}' != DB name='{db_name}' "
                    f"(slot={slot}, spec_id={sid})"
                )
            finally:
                if os.path.exists(local_bin):
                    os.unlink(local_bin)
        finally:
            await _deactivate(ws, sid)

    async def test_screw_cnt_in_mcu(self, ws, remote):
        """保存 screw_cnt=12 后，MCU 对应槽位的 screw_cnt 应等于 12。"""
        sid = _SID_MCU_VERIFY

        await _activate(ws, sid)
        try:
            payload = ScrewSpecFactory.default(sid)
            payload["detail_params"]["screw_cnt"] = 12
            resp = await ws.save_screw_param(sid, payload)
            assert resp.get("success") is True, f"save failed: {resp}"

            slot = await _get_slot_for_spec(ws, sid)
            if slot is None:
                pytest.skip(f"spec_id={sid} not mapped to MCU slot")

            with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
                local_bin = tmp.name

            try:
                remote_bin = await remote.dump_mcu_to_bin()
                await remote.download_mcu_bin(remote_bin, local_bin)

                verifier = McuVerifier(local_bin)
                got = verifier.get_screw_cnt(slot)
                assert got == 12, (
                    f"MCU slot={slot} screw_cnt={got}, expected 12"
                )
            finally:
                if os.path.exists(local_bin):
                    os.unlink(local_bin)
        finally:
            await _deactivate(ws, sid)

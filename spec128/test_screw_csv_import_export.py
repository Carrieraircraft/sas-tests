"""螺丝规格(PSET) 批量 CSV 导入/导出测试

覆盖：
  - 导出：success=True，返回 CSV 文本（download 模式），含表头与数据行
  - 往返一致性：导出 CSV 再导入，规格关键参数保持一致
  - 按 ID 覆盖：CSV 中 spec_id 决定写入槽位
  - 越界：spec_id 超出 0-127 的行被跳过并记录错误
  - 格式错误：缺少 spec_id 列时整体拒绝

测试 ID 全部取自 SAFE_TEST_RANGE (100-127)。
"""

import csv
import io

import pytest

from lib.constants import MsgType
from lib.helpers import ScrewSpecFactory

pytestmark = [pytest.mark.spec128, pytest.mark.p1]

_SID_A = 120
_SID_B = 121


def _skip_if_unauthorized(resp: dict) -> None:
    """该套件依赖写库权限(level 3)。若测试环境未登录，优雅跳过。"""
    if isinstance(resp, dict) and resp.get("error") == "未登录":
        pytest.skip("WS 会话未登录(需 level 3)，当前环境无法验证写库类用例")


async def _save_or_skip(ws, spec_id: int, payload: dict) -> dict:
    try:
        resp = await ws.save_screw_param(spec_id, payload)
    except TimeoutError:
        pytest.skip("screw_param_config 无响应(可能未登录)，跳过")
    _skip_if_unauthorized(resp)
    return resp


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


async def _export(ws, spec_ids=None) -> dict:
    msg = {"type": MsgType.SPEC_CSV_EXPORT, "target": "download"}
    if spec_ids is not None:
        msg["spec_ids"] = spec_ids
    return await ws.request(msg, MsgType.SPEC_CSV_EXPORT_RESPONSE)


async def _import(ws, csv_content: str) -> dict:
    resp = await ws.request(
        {
            "type": MsgType.SPEC_CSV_IMPORT,
            "source": "upload",
            "uploadUser": "test",
            "csvContent": csv_content,
        },
        MsgType.SPEC_CSV_IMPORT_RESPONSE,
    )
    _skip_if_unauthorized(resp)
    return resp


class TestCsvExport:
    async def test_export_returns_csv(self, ws):
        """导出指定规格，返回含表头与数据行的 CSV。"""
        await _activate(ws, _SID_A)
        await _save_or_skip(ws, _SID_A, ScrewSpecFactory.with_steps(_SID_A, 2))
        try:
            resp = await _export(ws, [_SID_A])
            assert resp.get("success") is True, f"export failed: {resp}"
            content = resp.get("csvContent", "")
            assert content, "csvContent should not be empty"
            rows = list(csv.reader(io.StringIO(content)))
            assert rows[0][0] == "spec_id", "header must start with spec_id"
            assert "screw_name" in rows[0]
            assert any(r and r[0] == str(_SID_A) for r in rows[1:]), "exported row missing"
        finally:
            await _deactivate(ws, _SID_A)

    async def test_export_all_active(self, ws):
        """不指定 spec_ids 时导出全部已激活规格。"""
        await _activate(ws, _SID_A)
        await _save_or_skip(ws, _SID_A, ScrewSpecFactory.default(_SID_A))
        try:
            resp = await _export(ws, None)
            assert resp.get("success") is True
            assert resp.get("count", 0) >= 1
        finally:
            await _deactivate(ws, _SID_A)


class TestCsvRoundTrip:
    async def test_export_then_import_consistent(self, ws):
        """导出 CSV 后导入到另一个 ID，关键参数应一致。"""
        await _activate(ws, _SID_A)
        await _save_or_skip(ws, _SID_A, ScrewSpecFactory.with_steps(_SID_A, 3))

        try:
            exp = await _export(ws, [_SID_A])
            assert exp.get("success") is True
            content = exp["csvContent"]

            # 改写 CSV 中的 spec_id：A -> B
            rows = list(csv.reader(io.StringIO(content)))
            header = rows[0]
            id_idx = header.index("spec_id")
            for r in rows[1:]:
                if r and r[id_idx] == str(_SID_A):
                    r[id_idx] = str(_SID_B)
            out = io.StringIO()
            csv.writer(out).writerows(rows)

            await _deactivate(ws, _SID_B)
            imp = await _import(ws, out.getvalue())
            assert imp.get("success") is True, f"import failed: {imp}"
            assert imp.get("importedCount", 0) >= 1

            # 校验 B 的 prog_cnt 与源一致
            src = await ws.get_screw_param(_SID_A)
            dst = await ws.get_screw_param(_SID_B)
            assert dst["data"]["prog_cnt"] == src["data"]["prog_cnt"]
        finally:
            await _deactivate(ws, _SID_A)
            await _deactivate(ws, _SID_B)


class TestCsvImportErrors:
    async def test_import_missing_spec_id_column(self, ws):
        """表头缺少 spec_id 列，整体拒绝。"""
        bad = "screw_name,prog_cnt\nfoo,1\n"
        resp = await _import(ws, bad)
        assert resp.get("success") is False
        assert resp.get("message"), "should report format error"

    async def test_import_out_of_range_id_skipped(self, ws):
        """spec_id 越界的行被跳过并记录错误。"""
        bad = "spec_id,screw_name,prog_cnt\n200,Oops,1\n"
        resp = await _import(ws, bad)
        # 该行应失败；整体 success=False（无成功行）
        assert resp.get("failedCount", 0) >= 1
        errors = resp.get("errors") or []
        assert any("200" in (e.get("error") or "") or e.get("line") == 2 for e in errors)

    async def test_import_empty_content(self, ws):
        """空内容应被拒绝。"""
        resp = await _import(ws, "")
        assert resp.get("success") is False

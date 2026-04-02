"""机种管理接口测试。"""

import pytest

pytestmark = [pytest.mark.machine_type, pytest.mark.p1]


class TestMachineType:
    async def test_machine_type_list_query(self, ws):
        resp = await ws.request(
            {"type": "machine_type_list_query"},
            "machine_type_list_response",
        )
        assert resp.get("type") == "machine_type_list_response"
        assert resp.get("success") is True
        assert isinstance(resp.get("data", []), list)

    async def test_machine_type_csv_export(self, ws):
        resp = await ws.request(
            {"type": "machine_type_csv_export"},
            "machine_type_csv_export_response",
        )
        assert resp.get("type") == "machine_type_csv_export_response"
        assert "success" in resp
        if resp.get("success"):
            assert "csvContent" in resp

    async def test_machine_type_csv_upload_invalid(self, ws):
        resp = await ws.request(
            {"type": "machine_type_csv_upload"},
            "machine_type_csv_upload_response",
        )
        assert resp.get("type") == "machine_type_csv_upload_response"
        assert resp.get("success") is False

    async def test_machine_type_constraints_query(self, ws):
        listing = await ws.request(
            {"type": "machine_type_list_query"},
            "machine_type_list_response",
        )
        assert listing.get("success") is True
        rows = listing.get("data", [])
        if rows:
            machine_type_id = rows[0].get("id")
            resp = await ws.request(
                {"type": "machine_type_constraints_query", "machineTypeId": machine_type_id},
                "machine_type_constraints_response",
            )
            assert resp.get("type") == "machine_type_constraints_response"
            assert resp.get("success") is True
            assert "constraints" in resp
        else:
            resp = await ws.request(
                {"type": "machine_type_constraints_query"},
                "machine_type_constraints_response",
            )
            assert resp.get("type") == "machine_type_constraints_response"
            assert resp.get("success") is False


"""条码绑定更新与查询。"""

import time

import pytest

pytestmark = [pytest.mark.barcode, pytest.mark.p1]


def _request_bindings_payload(bindings_from_query: list[dict]) -> list[dict]:
    payload = []
    for item in bindings_from_query:
        payload.append(
            {
                "key": item.get("barcode_key"),
                "target_id": item.get("screw_id"),
                "enabled": bool(item.get("enabled", True)),
                "policy": item.get("policy"),
                "max_screw_count": int(item.get("max_screw_count", 1) or 1),
                "ng_strategy": item.get("ng_strategy", "RETRY"),
            }
        )
    return payload


class TestBarcodeBindings:
    async def test_barcode_bindings_update_and_query(self, ws):
        query_req = {"type": "job_data_request", "data_type": "barcode_bindings", "work_mode": "SCREW_MODE"}
        original = await ws.request(query_req, "data_response")
        assert original.get("type") == "data_response"
        assert original.get("data_type") == "barcode_bindings"
        assert original.get("success") is True

        original_list = list(original.get("data", []))
        restore_payload = _request_bindings_payload(original_list)

        key = f"pytest-{int(time.time())}"
        new_payload = list(restore_payload)
        new_payload.append(
            {
                "key": key,
                "target_id": 120,
                "enabled": True,
                "policy": "ONE_TO_ONE",
                "max_screw_count": 1,
                "ng_strategy": "RETRY",
            }
        )

        try:
            update = await ws.request(
                {
                    "type": "barcode_bindings_update",
                    "work_mode": "SCREW_MODE",
                    "bindings": new_payload,
                    "modify_user": "pytest",
                },
                "barcode_bindings_update_response",
            )
            assert update.get("type") == "barcode_bindings_update_response"
            assert update.get("success") is True

            queried = await ws.request(query_req, "data_response")
            assert queried.get("success") is True
            keys = {x.get("barcode_key") for x in queried.get("data", [])}
            assert key in keys
        finally:
            await ws.request(
                {
                    "type": "barcode_bindings_update",
                    "work_mode": "SCREW_MODE",
                    "bindings": restore_payload,
                    "modify_user": "pytest",
                },
                "barcode_bindings_update_response",
            )

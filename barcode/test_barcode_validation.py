"""条码配置校验测试。"""

import pytest

pytestmark = [pytest.mark.barcode, pytest.mark.p1]


class TestBarcodeValidation:
    async def test_barcode_config_validation(self, ws):
        resp = await ws.request(
            {"type": "barcode_config_validation"},
            "barcode_config_validation_response",
        )
        assert resp.get("type") == "barcode_config_validation_response"
        assert resp.get("success") is True
        assert "is_valid" in resp
        assert "warnings" in resp
        assert "errors" in resp


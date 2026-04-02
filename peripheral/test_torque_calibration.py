"""扭力标定接口测试。"""

import pytest

pytestmark = [pytest.mark.peripheral, pytest.mark.p1, pytest.mark.hardware]


class TestTorqueCalibration:
    async def test_torque_calibration_save_missing_data(self, ws):
        resp = await ws.request(
            {"type": "torque_calibration_save"},
            "torque_calibration_save_response",
        )
        assert resp.get("type") == "torque_calibration_save_response"
        assert resp.get("success") is False
        assert "error" in resp


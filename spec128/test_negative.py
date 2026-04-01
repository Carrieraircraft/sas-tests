"""异常请求路径。"""

import pytest

from lib.constants import MsgType

pytestmark = [pytest.mark.spec128, pytest.mark.p2]


class TestNegative:
    async def test_screw_config_missing_fields(self, ws):
        r = await ws.request(
            {"type": MsgType.SCREW_PARAM_CONFIG, "mode": 1},
            MsgType.SCREW_PARAM_SAVE_RESPONSE,
        )
        assert r.get("success") is False

    async def test_module_config_invalid_id(self, ws):
        r = await ws.request_any(
            {
                "type": MsgType.MODULE_CONFIG,
                "module_id": 999,
                "product_name": "bad",
            },
            (MsgType.MODULE_CONFIG_RESPONSE, MsgType.MODULE_ERROR),
        )
        assert r.get("success") is False

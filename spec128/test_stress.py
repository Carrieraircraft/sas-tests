"""压力：批量请求与响应顺序。"""

import pytest

from lib.constants import MsgType, STRESS_WS_TIMEOUT, MAX_LIST_RESPONSE_MS
from lib.helpers import assert_response_time, ScrewSpecFactory

pytestmark = [pytest.mark.spec128, pytest.mark.p2, pytest.mark.stress]


@pytest.mark.timeout(120)
class TestStress:
    async def test_burst_get_screw_param_128(self, ws):
        msgs = [
            {"type": MsgType.SCREW_PARAM_GET, "specification_id": i}
            for i in range(128)
        ]
        responses = await ws.burst_same_response(
            msgs,
            MsgType.SCREW_PARAM_GET_RESPONSE,
            timeout_each=STRESS_WS_TIMEOUT,
        )
        assert len(responses) == 128
        ok = sum(1 for r in responses if r.get("success"))
        assert ok >= 120

    async def test_full_spec_list_performance(self, ws):
        await ws.get_spec_list()
        assert_response_time(ws.last_elapsed_ms, MAX_LIST_RESPONSE_MS)

    async def test_complex_spec_still_responds(self, ws):
        await ws.save_screw_param(127, ScrewSpecFactory.complex_full(127))
        r = await ws.get_screw_param(127)
        assert r.get("success") is True

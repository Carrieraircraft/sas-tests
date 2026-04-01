"""螺丝步骤参数往返。"""

import pytest

from lib.helpers import ScrewSpecFactory

pytestmark = [pytest.mark.spec128, pytest.mark.p3]


class TestScrewStep:
    async def test_steps_roundtrip(self, ws):
        sid = 120
        await ws.save_screw_param(sid, ScrewSpecFactory.with_steps(sid, 4))
        r = await ws.get_screw_steps(sid)
        assert r.get("type") == "screw_step_param_get_response"
        assert r.get("success") is True

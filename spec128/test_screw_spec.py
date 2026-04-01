"""螺丝规格 CRUD 与边界。"""

import pytest

from lib.helpers import ScrewSpecFactory

pytestmark = [pytest.mark.spec128, pytest.mark.p1]


class TestScrewSpecCrud:
    async def test_get_spec_boundaries(self, ws):
        for sid in (0, 127):
            r = await ws.get_screw_param(sid)
            assert r.get("type") == "screw_param_get_response"
            assert "success" in r

    async def test_save_and_roundtrip(self, ws):
        sid = 122
        payload = ScrewSpecFactory.with_steps(sid, 3)
        save_r = await ws.save_screw_param(sid, payload)
        assert save_r.get("success") is True, save_r
        got = await ws.get_screw_param(sid)
        assert got.get("success") is True
        assert got["data"]["prog_cnt"] == 3

    async def test_invalid_spec_id_rejected(self, ws):
        r = await ws.request(
            {"type": "screw_param_get", "specification_id": -1},
            "screw_param_get_response",
        )
        assert r.get("success") is False or r.get("error")

"""断电模拟：kill 后端进程后验证数据一致性（破坏性）。"""

import pytest

from lib.helpers import ScrewSpecFactory
from lib.ws_client import WSClient

pytestmark = [
    pytest.mark.spec128,
    pytest.mark.p2,
    pytest.mark.persistence,
    pytest.mark.destructive,
]


@pytest.mark.timeout(120)
class TestPowerLoss:
    async def test_screw_save_survives_kill_restart(self, ws_url, remote):
        sid = 126
        c = WSClient()
        await c.connect(ws_url)
        try:
            await c.save_screw_param(sid, ScrewSpecFactory.default(sid))
            got_before = await c.get_screw_param(sid)
            name_before = got_before["data"]["screw_name"]
            await remote.kill_backend()
            await remote.start_backend()
            await remote.wait_until_ready(ws_url, timeout=90)
        finally:
            await c.disconnect()

        c2 = WSClient()
        await c2.connect(ws_url)
        try:
            got_after = await c2.get_screw_param(sid)
            assert got_after.get("success") is True
            assert got_after["data"]["screw_name"] == name_before
        finally:
            await c2.disconnect()

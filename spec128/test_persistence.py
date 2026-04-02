"""持久化与冷启动：需 SSH 访问树莓派以重启后端。"""

import pytest

from lib.helpers import snapshot_spec_list

pytestmark = [
    pytest.mark.spec128,
    pytest.mark.p2,
    pytest.mark.persistence,
]


class TestColdStartConsistency:
    async def test_spec_list_stable_across_restart(self, ws, remote, ws_url, db_isolation):
        """重启后端后，规格列表应保持 128 条且顺序不变。"""
        before = await snapshot_spec_list(ws)
        assert len(before) == 128, f"pre-restart: expected 128, got {len(before)}"
        await remote.restart_backend()
        await remote.wait_until_ready(ws_url, timeout=60)
        await ws.disconnect()
        await ws.connect(ws_url)
        after = await snapshot_spec_list(ws)
        assert len(after) == 128, f"post-restart: expected 128, got {len(after)}"
        assert [x.get("value") for x in before] == [x.get("value") for x in after]

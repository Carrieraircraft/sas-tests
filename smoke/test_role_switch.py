"""角色切换（若后端未配置多角色则可能跳过断言）。"""

import pytest

from lib.constants import MsgType

pytestmark = pytest.mark.smoke


class TestRoleSwitch:
    async def test_role_switch_message_reaches_backend(self, ws):
        r = await ws.request(
            {
                "type": MsgType.ROLE_SWITCH,
                "data": {
                    "target_role": "operator",
                    "password": "",
                },
            },
            MsgType.ROLE_SWITCH_RESPONSE,
        )
        assert r.get("type") == MsgType.ROLE_SWITCH_RESPONSE

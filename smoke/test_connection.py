import pytest
from lib.constants import MsgType

pytestmark = pytest.mark.smoke


class TestConnection:
    """WebSocket 连接与心跳测试"""

    async def test_ws_connect(self, ws):
        """验证 WebSocket 能成功连接"""
        assert ws.connected

    async def test_heartbeat_ping_pong(self, ws):
        """验证心跳机制：发送 ping 后连接保持正常"""
        await ws.send({"type": MsgType.PING})
        import asyncio
        await asyncio.sleep(0.5)
        specs = await ws.get_spec_list()
        assert isinstance(specs, list)

    async def test_multiple_rapid_pings(self, ws):
        """验证连续快速 ping 不会导致连接异常"""
        for _ in range(10):
            await ws.send({"type": MsgType.PING})
        resp = await ws.get_spec_list()
        assert isinstance(resp, list)

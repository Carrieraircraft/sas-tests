"""已登录的 ws 夹具：后端对除 login/reconnect/heartbeat/ping 外的消息要求登录，
本目录用例测的是业务功能而非鉴权，因此覆盖根 conftest 的 ws，登录后再交给用例。"""

import pytest

from lib.ws_client import WSClient


@pytest.fixture(scope="function")
async def ws(ws_url):
    client = WSClient()
    await client.connect(ws_url)
    resp = await client.request(
        {"type": "login", "data": {"username": "admin", "password": "123"}},
        "login_response",
    )
    if not resp.get("success"):
        await client.disconnect()
        pytest.skip(f"login failed: {resp.get('error')}")
    yield client
    await client.disconnect()
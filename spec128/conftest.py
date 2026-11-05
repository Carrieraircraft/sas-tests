"""spec128 套件夹具：覆盖根 conftest 的 ws / ws_pair 为已登录客户端。

后端对除 login/reconnect/heartbeat/ping 外的消息要求登录，本套件测的是规格/模组业务，
不是鉴权，因此统一在夹具里用出厂 admin 登录。
"""

import pytest

from lib.ws_client import WSClient

_ADMIN = {"username": "admin", "password": "123"}


async def _login(url: str) -> WSClient:
    client = WSClient()
    await client.connect(url)
    resp = await client.request({"type": "login", "data": _ADMIN}, "login_response")
    if not resp.get("success"):
        await client.disconnect()
        pytest.skip(f"login failed: {resp.get('error')}")
    return client


@pytest.fixture(scope="function")
async def ws(ws_url):
    client = await _login(ws_url)
    yield client
    await client.disconnect()


@pytest.fixture(scope="function")
async def ws_pair(ws_url):
    a = await _login(ws_url)
    b = await _login(ws_url)
    yield a, b
    await b.disconnect()
    await a.disconnect()
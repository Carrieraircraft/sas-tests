"""network suite fixtures."""

import pytest

from lib.ws_client import WSClient

# 出厂默认管理员账号，与 tests/system/conftest.py 保持一致。
DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASSWORD = "123"


@pytest.fixture(scope="function")
async def ws_auth(ws_url):
    """已登录的 WebSocket 客户端。

    modbus_config_set 等配置类接口在未登录时一律回
    {"success": false, "error": "未登录"}，与 tests/system/conftest.py 的
    ws_auth 语义一致（此处独立定义一份，因为 conftest 只对同目录及子目录生效）。
    """
    client = WSClient()
    await client.connect(ws_url)

    resp = await client.request(
        {
            "type": "login",
            "data": {"username": DEFAULT_ADMIN_USER, "password": DEFAULT_ADMIN_PASSWORD},
        },
        "login_response",
    )
    if not resp.get("success"):
        await client.disconnect()
        pytest.skip(f"login failed: {resp.get('error')}")

    yield client
    await client.disconnect()

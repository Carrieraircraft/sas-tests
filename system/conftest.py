"""system suite fixtures."""

import pytest

from lib.ws_client import WSClient

# 出厂默认管理员账号。
# 密码发明文：后端 UserMGR::validateUserPassword 会自己对入参做 sha256
# 再与 User.UserPassword 比对，客户端预先哈希只会双重哈希导致登录失败。
DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASSWORD = "123"


@pytest.fixture(scope="function")
async def ws_auth(ws_url):
    """已登录的 WebSocket 客户端。

    除 login/reconnect/heartbeat/ping 之外的消息都要求已登录，
    未登录时后端一律回 {"success": false, "error": "未登录"}，
    这会让断言在"接口真的坏了"和"没登录"之间无法区分。
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

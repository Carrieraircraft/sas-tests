"""username_list 接口测试。

这个接口是为了让登录页把用户名做成下拉，省去在触摸屏上手输，因此它必须
**在未登录状态下**可用——这正是它区别于 account_list 的地方。

同时它是唯一一个免鉴权就能读数据库的接口，所以要盯死返回面：
只许给用户名/显示名/角色，一旦哪天有人顺手把 UserInfo 整个塞进响应，
密码哈希就会在登录页上公开泄露。
"""

import pytest

pytestmark = [pytest.mark.system, pytest.mark.p0]

# 绝不允许出现在响应里的字段名（密码哈希及其常见别名）
FORBIDDEN_KEYS = {
    "password",
    "userpassword",
    "user_password",
    "passwordhash",
    "password_hash",
    "defaultvalue",
    "default_value",
}


class TestUsernameList:
    async def test_available_without_login(self, ws):
        """未登录必须能拿到列表，否则登录页的下拉永远是空的。"""
        resp = await ws.request({"type": "username_list", "data": {}},
                                "username_list_response")
        assert resp.get("success") is True, resp.get("error")

        accounts = (resp.get("data") or {}).get("usernames")
        assert isinstance(accounts, list)
        assert accounts, "至少应有出厂管理员账号"

        for item in accounts:
            assert item.get("username"), f"存在空用户名: {item}"
            assert "display_name" in item
            assert "role" in item

    async def test_never_leaks_password(self, ws):
        """免鉴权接口的返回面必须锁死，不能带出任何密码相关字段。"""
        resp = await ws.request({"type": "username_list", "data": {}},
                                "username_list_response")

        for item in (resp.get("data") or {}).get("usernames") or []:
            leaked = {k for k in item if k.lower() in FORBIDDEN_KEYS}
            assert not leaked, f"响应泄露了敏感字段 {leaked}: {item}"

    async def test_account_list_still_requires_permission(self, ws):
        """新增免鉴权接口不能顺带把 account_list 的门槛也放开。"""
        resp = await ws.request({"type": "account_list", "data": {}},
                                "account_list_response")
        assert resp.get("success") is False
        assert resp.get("error")

    async def test_matches_account_list_when_authorized(self, ws_auth):
        """与 account_list 的启用账号集合应当一致，避免两个接口各说一套。"""
        brief = await ws_auth.request({"type": "username_list", "data": {}},
                                      "username_list_response")
        full = await ws_auth.request({"type": "account_list", "data": {}},
                                     "account_list_response")
        if not full.get("success"):
            pytest.skip(f"account_list 不可用: {full.get('error')}")

        brief_names = {i["username"] for i in (brief.get("data") or {}).get("usernames") or []}
        active_names = {
            i["username"]
            for i in (full.get("data") or {}).get("accounts") or []
            if i.get("is_active")
        }
        assert brief_names == active_names

"""网络状态与网络管理聚合接口测试。"""

import pytest

pytestmark = [pytest.mark.network, pytest.mark.p1]


class TestNetworkStatus:
    async def test_network_request_ethernet_query(self, ws):
        resp = await ws.request(
            {"type": "network_request", "action": "query", "target": "ethernet"},
            "network_response",
        )
        assert resp.get("type") == "network_response"
        assert resp.get("target") == "ethernet"
        assert "success" in resp

    async def test_header_network_mode_query(self, ws):
        resp = await ws.request(
            {"type": "header_network_mode_query"},
            "header_network_mode_query_response",
        )
        assert resp.get("type") == "header_network_mode_query_response"
        assert "success" in resp
        if resp.get("success"):
            assert "mode" in resp.get("data", {})

    async def test_header_network_mode_set_roundtrip(self, ws):
        current = await ws.request(
            {"type": "header_network_mode_query"},
            "header_network_mode_query_response",
        )
        if not current.get("success"):
            pytest.skip(f"header mode query unavailable: {current.get('error')}")
        mode = current.get("data", {}).get("mode", "controller")
        resp = await ws.request(
            {"type": "header_network_mode_set", "mode": mode, "user": "pytest"},
            "header_network_mode_set_response",
        )
        assert resp.get("type") == "header_network_mode_set_response"
        assert resp.get("success") is True

    async def test_network_status_query_push(self, ws):
        await ws.send({"type": "network_status_query"})
        pushed = await ws.wait_for_condition(
            lambda m: m.get("type") == "network_status_push",
            timeout=5.0,
        )
        assert pushed.get("type") == "network_status_push"
        assert "data" in pushed


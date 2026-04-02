"""WiFi 热点/STA 配置测试。"""

import pytest

pytestmark = [pytest.mark.network, pytest.mark.p1]


class TestWiFi:
    async def test_wifi_hotspot_query(self, ws):
        resp = await ws.request({"type": "wifi_hotspot_query"}, "wifi_hotspot_query_response")
        assert resp.get("type") == "wifi_hotspot_query_response"
        assert "success" in resp

    async def test_wifi_station_query(self, ws):
        resp = await ws.request({"type": "wifi_station_query"}, "wifi_station_query_response")
        assert resp.get("type") == "wifi_station_query_response"
        assert "success" in resp

    async def test_wifi_hotspot_set_invalid_payload(self, ws):
        resp = await ws.request({"type": "wifi_hotspot_set"}, "wifi_hotspot_set_response")
        assert resp.get("type") == "wifi_hotspot_set_response"
        assert resp.get("success") is False

    async def test_wifi_station_set_invalid_payload(self, ws):
        resp = await ws.request({"type": "wifi_station_set"}, "wifi_station_set_response")
        assert resp.get("type") == "wifi_station_set_response"
        assert resp.get("success") is False


"""PFOP 配置测试。"""

import pytest

pytestmark = [pytest.mark.network, pytest.mark.p1]


class TestPFOPConfig:
    async def test_pfop_config_query(self, ws):
        resp = await ws.request({"type": "pfop_config_query"}, "pfop_config_query_response")
        assert resp.get("type") == "pfop_config_query_response"
        assert "success" in resp

    async def test_pfop_config_set_invalid_payload(self, ws):
        resp = await ws.request({"type": "pfop_config_set"}, "pfop_config_set_response")
        assert resp.get("type") == "pfop_config_set_response"
        assert resp.get("success") is False


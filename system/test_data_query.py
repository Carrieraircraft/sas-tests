"""数据查询接口测试。"""

import pytest

pytestmark = [pytest.mark.system, pytest.mark.p1]


class TestDataQuery:
    async def test_job_data_recent(self, ws):
        resp = await ws.request(
            {"type": "job_data_request", "data_type": "job_data_recent", "limit": 5},
            "data_response",
        )
        assert resp.get("type") == "data_response"
        assert resp.get("data_type") == "job_data_recent"
        assert "success" in resp

    async def test_job_data_unknown_type(self, ws):
        resp = await ws.request(
            {"type": "job_data_request", "data_type": "unknown_type"},
            "data_response",
        )
        assert resp.get("type") == "data_response"
        assert resp.get("success") is False


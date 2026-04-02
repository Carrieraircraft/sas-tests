"""端口配置测试。"""

import pytest

pytestmark = [pytest.mark.peripheral, pytest.mark.p1]


class TestPortConfig:
    async def test_port_config_get(self, ws):
        resp = await ws.request({"type": "port_config_get"}, "port_config_get_response")
        assert resp.get("type") == "port_config_get_response"
        assert "success" in resp
        if resp.get("success") is False:
            pytest.skip(f"port_config_get unavailable: {resp.get('error')}")
        data = resp.get("data", {})
        assert "inputs" in data
        assert "outputs" in data

    async def test_port_config_save_roundtrip(self, ws):
        base = await ws.request({"type": "port_config_get"}, "port_config_get_response")
        if base.get("success") is False:
            pytest.skip(f"port_config_get unavailable: {base.get('error')}")

        before = base.get("data", {})
        inputs = list(before.get("inputs", []))
        outputs = list(before.get("outputs", []))
        if not inputs and not outputs:
            pytest.skip("no port config records to update")

        new_inputs = [dict(x) for x in inputs]
        new_outputs = [dict(x) for x in outputs]
        if new_inputs:
            new_inputs[0]["enabled"] = not bool(new_inputs[0].get("enabled", False))
        else:
            new_outputs[0]["enabled"] = not bool(new_outputs[0].get("enabled", False))

        payload = {"inputs": new_inputs, "outputs": new_outputs}
        save = await ws.request({"type": "port_config_save", "data": payload}, "port_config_save_response")
        assert save.get("type") == "port_config_save_response"
        assert save.get("success") is True

        verify = await ws.request({"type": "port_config_get"}, "port_config_get_response")
        assert verify.get("success") is True
        if new_inputs:
            assert bool(verify["data"]["inputs"][0]["enabled"]) == bool(new_inputs[0]["enabled"])
        else:
            assert bool(verify["data"]["outputs"][0]["enabled"]) == bool(new_outputs[0]["enabled"])

        await ws.request({"type": "port_config_save", "data": before}, "port_config_save_response")


"""统一模组 CRUD。"""

import pytest

from lib.helpers import ModuleFactory

pytestmark = [pytest.mark.spec128, pytest.mark.p1]


class TestModuleCrud:
    async def test_save_manual_and_get(self, ws):
        mid = 123
        r = await ws.save_module(mid, ModuleFactory.manual(mid, [10, 11, 12]))
        assert r.get("success") is True, r
        g = await ws.get_module(mid)
        assert g.get("success") is True
        assert g["data"]["product_name"].startswith("ManualModule")

    async def test_torque_arm_module_fields(self, ws):
        mid = 124
        r = await ws.save_module(mid, ModuleFactory.torque_arm(mid, 4))
        assert r.get("success") is True
        g = await ws.get_module(mid)
        assert g["data"].get("torque_arm_config") is not None

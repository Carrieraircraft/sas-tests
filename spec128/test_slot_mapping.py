"""槽位相关：抖动、并发写入（黑盒，不依赖 MCU 调试接口）。"""

import asyncio
import time

import pytest

from lib.constants import MAX_CONCURRENT_RESPONSE_MS, SAFE_TEST_RANGE
from lib.helpers import ScrewSpecFactory, ModuleFactory, assert_response_time

pytestmark = [pytest.mark.spec128, pytest.mark.p0]


class TestSlotThrashing:
    """连续切换多颗逻辑规格写入，验证仍可稳定响应。"""

    async def test_sequential_save_many_specs(self, ws):
        """顺序保存 SAFE 区间内 20 个规格，全部成功且单次耗时在阈值内。"""
        ids = list(range(100, 120))
        for sid in ids:
            t0 = time.monotonic()
            r = await ws.save_screw_param(sid, ScrewSpecFactory.default(sid))
            elapsed = (time.monotonic() - t0) * 1000
            assert r.get("success") is True, r
            assert_response_time(elapsed, MAX_CONCURRENT_RESPONSE_MS)


class TestConcurrentClients:
    """双连接并发操作。"""

    async def test_concurrent_different_modules(self, ws_pair):
        """两个客户端同时写入不同 module_id，应均成功。"""
        a, b = ws_pair
        ra, rb = await asyncio.gather(
            a.save_module(100, ModuleFactory.manual(100, [0, 1, 2])),
            b.save_module(101, ModuleFactory.manual(101, [3, 4, 5])),
        )
        assert ra.get("type") == "module_config_response"
        assert ra.get("success") is True
        assert rb.get("type") == "module_config_response"
        assert rb.get("success") is True

    async def test_concurrent_same_spec_id_writes(self, ws_pair):
        """两客户端先后写入同一 spec_id，至少有一次成功，最终读取为合法数据。"""
        a, b = ws_pair
        await asyncio.gather(
            a.save_screw_param(120, ScrewSpecFactory.default(120)),
            b.save_screw_param(120, ScrewSpecFactory.random(120)),
        )
        got = await a.get_screw_param(120)
        assert got.get("success") is True
        assert got.get("data", {}).get("screw_name")

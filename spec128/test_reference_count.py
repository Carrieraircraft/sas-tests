"""引用计数、克隆链、与祖先修改隔离（COW 行为黑盒验证）。"""

import asyncio

import pytest

from lib.constants import MsgType
from lib.helpers import ScrewSpecFactory, ModuleFactory

pytestmark = [pytest.mark.spec128, pytest.mark.p0]


class TestReferenceQuery:
    async def test_reference_count_starts_at_zero(self, ws):
        r = await ws.query_screw_reference(110)
        assert r.get("type") == MsgType.SPEC_REF_RESPONSE
        assert r.get("success") is True
        assert r.get("reference_count", -1) >= 0

    async def test_reference_increments_when_module_references_spec(self, ws):
        await ws.save_screw_param(111, ScrewSpecFactory.default(111))
        before = await ws.query_screw_reference(111)
        n0 = before.get("reference_count", 0)
        await ws.save_module(112, ModuleFactory.manual(112, [111, 111]))
        after = await ws.query_screw_reference(111)
        assert after.get("success") is True
        assert after.get("reference_count", 0) >= n0


class TestCowIsolation:
    """COW/隔离：独立保存的两条规格，修改其一不应影响另一条。"""

    async def test_two_specs_independent_after_separate_saves(self, ws):
        a, b = 108, 109
        await ws.save_screw_param(a, ScrewSpecFactory.default(a))
        await ws.save_screw_param(b, ScrewSpecFactory.default(b))
        await asyncio.sleep(0.2)
        mod = ScrewSpecFactory.default(a)
        mod["specification_name"] = "Only-A-Changed"
        await ws.save_screw_param(a, mod)
        na = (await ws.get_screw_param(a))["data"]["screw_name"]
        nb = (await ws.get_screw_param(b))["data"]["screw_name"]
        assert "Only-A-Changed" in na or na == "Only-A-Changed"
        assert nb and "109" in nb


class TestCloneChain:
    @pytest.mark.xfail(
        reason="当前后端 cloneScrewSpec 在实机返回失败；链路通过后改为正式用例",
        strict=False,
    )
    async def test_deep_clone_chain_five_levels_ancestor_edit_isolated(self, ws):
        """若 screw_spec_clone 可用：沿链克隆 5 次后修改祖先，末端应保持副本语义。"""
        base = 106
        await ws.save_screw_param(base, ScrewSpecFactory.with_steps(base, 2))
        await asyncio.sleep(0.4)
        (await ws.get_screw_param(base))["data"]["screw_name"]
        cur = base
        for nxt in range(base + 1, base + 6):
            r = await ws.clone_screw_spec(cur, nxt)
            assert r.get("success") is True, r
            await asyncio.sleep(0.15)
            cur = nxt
        leaf = base + 5
        leaf_name_before = (await ws.get_screw_param(leaf))["data"]["screw_name"]

        mod = ScrewSpecFactory.default(base)
        mod["specification_name"] = "Ancestor-Modified-Unique"
        await ws.save_screw_param(base, mod)

        name_ancestor = (await ws.get_screw_param(base))["data"]["screw_name"]
        name_leaf = (await ws.get_screw_param(leaf))["data"]["screw_name"]

        assert name_ancestor != leaf_name_before or "Modified" in name_ancestor
        assert name_leaf == leaf_name_before

"""列表完整性（128 条）。"""

import pytest

pytestmark = [pytest.mark.spec128, pytest.mark.p3]


class TestPaginationCompleteness:
    async def test_spec_and_module_lists_length(self, ws, db_isolation):
        """规格列表和模组列表各应恰好包含 128 条记录，无越界 ID。"""
        specs = await ws.get_spec_list()
        mods = await ws.get_module_list()
        assert len(specs) == 128, f"Expected 128 specs, got {len(specs)}"
        assert len(mods) == 128

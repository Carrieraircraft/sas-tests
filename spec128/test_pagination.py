"""列表完整性（128 条）。"""

import pytest

pytestmark = [pytest.mark.spec128, pytest.mark.p3]


class TestPaginationCompleteness:
    async def test_spec_and_module_lists_length(self, ws):
        specs = await ws.get_spec_list()
        mods = await ws.get_module_list()
        assert len(specs) == 128
        assert len(mods) == 128

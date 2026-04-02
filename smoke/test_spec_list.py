import pytest
from lib.constants import MsgType, MAX_LIST_RESPONSE_MS
from lib.helpers import assert_response_time

pytestmark = pytest.mark.smoke


class TestSpecList:
    """螺丝规格列表可达性测试"""

    async def test_get_spec_list(self, ws):
        """验证能获取螺丝规格列表"""
        specs = await ws.get_spec_list()
        assert isinstance(specs, list)

    async def test_spec_list_has_128_entries(self, ws, db_isolation):
        """验证规格列表恰好包含 128 条记录（后端不应返回越界 ID）"""
        specs = await ws.get_spec_list()
        assert len(specs) == 128, f"Expected 128 specs, got {len(specs)}"

    async def test_spec_list_ids_range(self, ws, db_isolation):
        """验证规格 ID 严格在 0-127 范围内，无越界条目"""
        specs = await ws.get_spec_list()
        ids = [s.get("value") for s in specs if s.get("value") is not None]
        assert len(ids) == 128
        assert min(ids) == 0
        assert max(ids) == 127
        assert len(set(ids)) == 128, f"IDs not unique: {sorted(ids)}"

    async def test_spec_list_response_time(self, ws):
        """验证规格列表响应时间在阈值内"""
        await ws.get_spec_list()
        assert_response_time(ws.last_elapsed_ms, MAX_LIST_RESPONSE_MS)

    async def test_get_module_list(self, ws):
        """验证能获取模组列表"""
        modules = await ws.get_module_list()
        assert isinstance(modules, list)

    async def test_module_list_has_128_entries(self, ws):
        """验证模组列表包含 128 条记录"""
        modules = await ws.get_module_list()
        assert len(modules) == 128, f"Expected 128 modules, got {len(modules)}"

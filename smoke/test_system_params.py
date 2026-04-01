import pytest
from lib.constants import MsgType

pytestmark = pytest.mark.smoke


class TestSystemParams:
    """系统参数读取测试"""

    async def test_get_system_params(self, ws):
        """验证能获取系统参数"""
        params = await ws.get_system_params()
        assert params is not None
        assert isinstance(params, dict)

    async def test_system_params_has_data(self, ws):
        """验证系统参数包含有效数据"""
        params = await ws.get_system_params()
        assert len(params) > 0

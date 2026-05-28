"""条码 AutoBind 开关读写测试。

覆盖目标 (功能性):
- BarcodeAutoBind / BarcodeAutoBindNGStrategy 系统参数默认存在 (后端 initializeDefaultSystemParams 注入)
- 通过 system_params_batch_update 写入 BarcodeAutoBind=true / false 后, get_system_params 立即可见
- 写回原值, 不留副作用

注: 实际扫码 → ValidateBarcode → AutoBind 派生 target_id 的端到端联调
    依赖硬件状态机 (USB/EIP scan → IdleWaitJobState), 在树莓派现场 R5 阶段验证.
"""

import pytest

from tests.lib.ws_client import MsgType

pytestmark = [pytest.mark.barcode, pytest.mark.p1]


class TestBarcodeAutoBind:
    async def test_autobind_default_params_exist(self, ws):
        """默认参数应当存在: BarcodeAutoBind=false, BarcodeAutoBindNGStrategy=RETRY."""
        resp = await ws.get_system_params()
        assert resp.get("success") is True
        data = resp.get("data") or {}
        # 后端 initializeDefaultSystemParams 应已写入这两个参数
        assert "BarcodeAutoBind" in data, "BarcodeAutoBind 系统参数缺失,后端默认初始化未执行"
        assert "BarcodeAutoBindNGStrategy" in data, "BarcodeAutoBindNGStrategy 系统参数缺失"
        # 默认值不应破坏现网
        assert data.get("BarcodeAutoBind") in ("true", "false")
        assert data.get("BarcodeAutoBindNGStrategy") in ("RETRY", "SKIP", "HALT")

    async def test_autobind_toggle_on_then_off(self, ws):
        """开/关 AutoBind 后系统参数能正确读回,完成后还原."""
        # 读取原始值
        original = await ws.get_system_params()
        original_value = (original.get("data") or {}).get("BarcodeAutoBind", "false")

        try:
            # 1) 打开 AutoBind
            await ws.request(
                {
                    "type": MsgType.SYSTEM_PARAMS_BATCH_UPDATE,
                    "params": [
                        {"param_name": "BarcodeAutoBind", "param_value": "true"},
                    ],
                    "modify_user": "pytest_autobind",
                },
                MsgType.SYSTEM_PARAMS_BATCH_UPDATE_RESPONSE,
            )
            after_on = await ws.get_system_params()
            assert (after_on.get("data") or {}).get("BarcodeAutoBind") == "true"

            # 2) 关闭 AutoBind
            await ws.request(
                {
                    "type": MsgType.SYSTEM_PARAMS_BATCH_UPDATE,
                    "params": [
                        {"param_name": "BarcodeAutoBind", "param_value": "false"},
                    ],
                    "modify_user": "pytest_autobind",
                },
                MsgType.SYSTEM_PARAMS_BATCH_UPDATE_RESPONSE,
            )
            after_off = await ws.get_system_params()
            assert (after_off.get("data") or {}).get("BarcodeAutoBind") == "false"
        finally:
            # 还原
            await ws.request(
                {
                    "type": MsgType.SYSTEM_PARAMS_BATCH_UPDATE,
                    "params": [
                        {"param_name": "BarcodeAutoBind", "param_value": original_value},
                    ],
                    "modify_user": "pytest_autobind",
                },
                MsgType.SYSTEM_PARAMS_BATCH_UPDATE_RESPONSE,
            )

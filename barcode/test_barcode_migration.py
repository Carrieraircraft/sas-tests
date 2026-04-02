"""条码配置迁移测试。"""

import pytest

pytestmark = [pytest.mark.barcode, pytest.mark.p1]


class TestBarcodeMigration:
    async def test_barcode_config_migration(self, ws):
        resp = await ws.request(
            {"type": "barcode_config_migration", "default_max_screw_count": 5},
            "barcode_config_migration_response",
        )
        assert resp.get("type") == "barcode_config_migration_response"
        assert "success" in resp


"""首航数据库迁移：需提供旧版 SAS.db 时扩展。"""

import os

import pytest

pytestmark = [pytest.mark.spec128, pytest.mark.p3]


@pytest.mark.skipif(
    not os.environ.get("SAS_LEGACY_DB_PATH"),
    reason="设置环境变量 SAS_LEGACY_DB_PATH 指向含旧表的数据库文件后可启用",
)
class TestMigrationPlaceholder:
    async def test_placeholder(self, ws):
        assert await ws.get_spec_list()

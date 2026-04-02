"""USB 与升级流程（非破坏性）测试。"""

import pytest

pytestmark = [pytest.mark.system, pytest.mark.p1]


class TestUsbUpgrade:
    async def test_usb_status_check(self, ws):
        resp = await ws.request({"type": "usb_status_check"}, "usb_status_check_response")
        assert resp.get("type") == "usb_status_check_response"
        assert "success" in resp

    async def test_usb_files_list_missing_path(self, ws):
        resp = await ws.request({"type": "usb_files_list"}, "usb_files_list_response")
        assert resp.get("type") == "usb_files_list_response"
        assert resp.get("success") is False

    async def test_usb_image_read_missing_path(self, ws):
        resp = await ws.request({"type": "usb_image_read"}, "usb_image_read_response")
        assert resp.get("type") == "usb_image_read_response"
        assert resp.get("success") is False

    async def test_upgrade_scan_packages_missing_mount_path(self, ws):
        resp = await ws.request_any(
            {"type": "upgrade:scan_packages"},
            ("upgrade_scan_error", "upgrade:scan_result"),
        )
        assert resp.get("type") in ("upgrade_scan_error", "upgrade:scan_result")
        if resp.get("type") == "upgrade:scan_result":
            assert resp.get("success") is False
        else:
            assert resp.get("success") is False


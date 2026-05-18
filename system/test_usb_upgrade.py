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


class TestUsbImageSelector:
    """USB 图像选择器完整流程测试。

    覆盖模组配置页面"从USB选择"功能的三步流程：
    1. usb_status_check → 检测挂载状态
    2. usb_files_list   → 扫描图像文件
    3. usb_image_read    → 读取图像为 Base64
    """

    async def test_usb_status_check_returns_mount_info(self, ws):
        """USB 状态检查应返回 isMounted 字段"""
        resp = await ws.request(
            {"type": "usb_status_check"},
            "usb_status_check_response",
        )
        assert resp["success"] is True
        assert "data" in resp
        assert "isMounted" in resp["data"]

    async def test_usb_status_check_mounted_has_path(self, ws):
        """若 USB 已挂载，应返回 mountPath 和 deviceName"""
        resp = await ws.request(
            {"type": "usb_status_check"},
            "usb_status_check_response",
        )
        assert resp["success"] is True
        if resp["data"]["isMounted"]:
            assert resp["data"]["mountPath"], "mountPath should not be empty"
            assert resp["data"]["deviceName"], "deviceName should not be empty"

    async def test_usb_files_list_with_valid_path(self, ws):
        """使用有效挂载路径扫描图像文件列表"""
        status = await ws.request(
            {"type": "usb_status_check"},
            "usb_status_check_response",
        )
        if not status["success"] or not status["data"]["isMounted"]:
            pytest.skip("USB not mounted")

        mount_path = status["data"]["mountPath"]
        resp = await ws.request(
            {"type": "usb_files_list", "mount_path": mount_path, "recursive": True},
            "usb_files_list_response",
            timeout=15,
        )
        assert resp["success"] is True
        assert isinstance(resp["data"], list)
        assert "count" in resp

    async def test_usb_files_list_returns_image_info(self, ws):
        """扫描结果中每个文件应包含 name/path/size 字段"""
        status = await ws.request(
            {"type": "usb_status_check"},
            "usb_status_check_response",
        )
        if not status["success"] or not status["data"]["isMounted"]:
            pytest.skip("USB not mounted")

        mount_path = status["data"]["mountPath"]
        resp = await ws.request(
            {"type": "usb_files_list", "mount_path": mount_path, "recursive": True},
            "usb_files_list_response",
            timeout=15,
        )
        assert resp["success"] is True
        if len(resp["data"]) == 0:
            pytest.skip("No image files on USB")

        img = resp["data"][0]
        assert "name" in img
        assert "path" in img
        assert "size" in img
        assert img["size"] > 0

    async def test_usb_image_read_returns_base64(self, ws):
        """读取 USB 上的图像文件应返回 Base64 data URI"""
        status = await ws.request(
            {"type": "usb_status_check"},
            "usb_status_check_response",
        )
        if not status["success"] or not status["data"]["isMounted"]:
            pytest.skip("USB not mounted")

        mount_path = status["data"]["mountPath"]
        files_resp = await ws.request(
            {"type": "usb_files_list", "mount_path": mount_path, "recursive": True},
            "usb_files_list_response",
            timeout=15,
        )
        if not files_resp["success"] or len(files_resp["data"]) == 0:
            pytest.skip("No image files on USB")

        image_path = files_resp["data"][0]["path"]
        resp = await ws.request(
            {"type": "usb_image_read", "image_path": image_path},
            "usb_image_read_response",
            timeout=20,
        )
        assert resp["success"] is True
        assert "data" in resp
        base64_str = resp["data"]["base64"]
        assert base64_str.startswith("data:image/"), \
            f"Expected data URI, got: {base64_str[:50]}"

    async def test_usb_image_read_invalid_path(self, ws):
        """读取不存在的图像路径应返回失败"""
        resp = await ws.request(
            {"type": "usb_image_read", "image_path": "/media/usb/nonexistent_12345.png"},
            "usb_image_read_response",
        )
        assert resp["success"] is False

    async def test_usb_files_list_invalid_mount_path(self, ws):
        """使用不存在的挂载路径应返回空列表或失败"""
        resp = await ws.request(
            {"type": "usb_files_list", "mount_path": "/media/nonexistent_usb_xyz"},
            "usb_files_list_response",
        )
        assert resp["success"] is True and len(resp["data"]) == 0 \
            or resp["success"] is False

    async def test_full_image_select_flow(self, ws):
        """端到端：状态检查 → 文件列表 → 图像读取完整流程"""
        # Step 1: 检查 USB 状态
        status = await ws.request(
            {"type": "usb_status_check"},
            "usb_status_check_response",
        )
        assert status["success"] is True
        if not status["data"]["isMounted"]:
            pytest.skip("USB not mounted")

        # Step 2: 获取图像文件列表
        mount_path = status["data"]["mountPath"]
        files_resp = await ws.request(
            {"type": "usb_files_list", "mount_path": mount_path, "recursive": True},
            "usb_files_list_response",
            timeout=15,
        )
        assert files_resp["success"] is True
        assert isinstance(files_resp["data"], list)
        if len(files_resp["data"]) == 0:
            pytest.skip("No image files on USB")

        # Step 3: 读取第一张图像
        first_image = files_resp["data"][0]
        read_resp = await ws.request(
            {"type": "usb_image_read", "image_path": first_image["path"]},
            "usb_image_read_response",
            timeout=20,
        )
        assert read_resp["success"] is True
        assert read_resp["data"]["base64"].startswith("data:image/")


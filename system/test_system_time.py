"""系统时间接口测试。

覆盖点集中在几件曾经出过问题的事：
  1. get 返回的必须是设备真实时间（与运行机器差距不能大到离谱）
  2. 非法日期（如 2 月 31 日）必须明确报失败，而不是被 date 命令悄悄规范化
  3. calibrate 必须说清时间取自哪里（发起端 PC 还是某台 NTP）与偏移量，
     否则无法分辨"真的校准了"和"命令不存在但报成功"
  4. 时区可配置：德国现场按本地时间手动设时，设备却按 UTC+8 解释，
     后台 NTP 一校准就跳 6 小时
  5. 同步模式：手动设时后后台不能再自动授时把时间改掉
"""

import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

pytestmark = [pytest.mark.system, pytest.mark.p1]

# 回退 NTP 时后端最多花 12s 试完候选池，留足余量
CALIBRATE_TIMEOUT = 25.0


class TestSystemTime:
    async def test_system_time_get(self, ws_auth):
        resp = await ws_auth.request({"type": "system_time_get"}, "system_time_get_response")
        assert resp.get("type") == "system_time_get_response"
        assert resp.get("success") is True

        data = resp.get("data") or {}
        for field in ("year", "month", "day", "hour", "minute", "second", "timestamp"):
            assert field in data, f"缺少字段 {field}"

        assert 2024 <= data["year"] <= 2100
        assert 1 <= data["month"] <= 12
        assert 1 <= data["day"] <= 31

        # timestamp 必须是毫秒级 Unix 时间戳，且与本机时间在同一量级
        # （允许 1 天误差：设备可能尚未校时，但不能是 0 或 1970）
        local_ms = time.time() * 1000
        assert abs(data["timestamp"] - local_ms) < 86400_000, (
            f"设备时间与本机相差过大: device={data['timestamp']} local={local_ms}"
        )

    async def test_system_time_set_missing_data(self, ws_auth):
        resp = await ws_auth.request({"type": "system_time_set"}, "system_time_set_response")
        assert resp.get("type") == "system_time_set_response"
        assert resp.get("success") is False
        assert resp.get("error")

    async def test_system_time_set_nonexistent_date(self, ws_auth):
        """2 月 31 日各字段都在合法范围内，但日期不存在，必须被拒绝。"""
        resp = await ws_auth.request(
            {
                "type": "system_time_set",
                "data": {
                    "year": 2026,
                    "month": 2,
                    "day": 31,
                    "hour": 12,
                    "minute": 0,
                    "second": 0,
                },
            },
            "system_time_set_response",
        )
        assert resp.get("success") is False
        assert resp.get("error")

    async def test_system_time_set_out_of_range(self, ws_auth):
        resp = await ws_auth.request(
            {
                "type": "system_time_set",
                "data": {
                    "year": 1999,
                    "month": 1,
                    "day": 1,
                    "hour": 0,
                    "minute": 0,
                    "second": 0,
                },
            },
            "system_time_set_response",
        )
        assert resp.get("success") is False

    async def test_calibrate_from_client_time(self, ws_auth):
        """带上发起端时间戳时必须直接采用它，不依赖外网。

        现场多为纯内网，设备连不上公网 NTP，这条路径是校时能否用的关键，
        因此断言"必须成功"而不是"成功或失败都行"。
        """
        client_ms = int(time.time() * 1000)
        resp = await ws_auth.request(
            {
                "type": "system_time_calibrate",
                "locale": "zh-CN",
                "clientEpochMs": client_ms,
            },
            "system_time_calibrate_response",
            timeout=CALIBRATE_TIMEOUT,
        )
        assert resp.get("success") is True, resp.get("error")
        assert resp.get("source") == "client", "应采用发起端时间而非回退 NTP"
        assert isinstance(resp.get("offsetMs"), (int, float))
        assert "mcuSynced" in resp

        # 校准后设备时间应贴近本机；阈值放到 5s 以容纳网络往返与用例调度
        data = resp.get("data") or {}
        assert 2024 <= (data.get("year") or 0) <= 2100
        assert abs(data.get("timestamp", 0) - time.time() * 1000) < 5_000

    async def test_calibrate_rejects_implausible_client_time(self, ws_auth):
        """发起端时钟本身是错的（1970 年）时不能采用，须回退 NTP。"""
        resp = await ws_auth.request(
            {"type": "system_time_calibrate", "locale": "zh-CN", "clientEpochMs": 1000},
            "system_time_calibrate_response",
            timeout=CALIBRATE_TIMEOUT,
        )
        assert resp.get("source") == "ntp", "不可信的发起端时间不应被采用"

    async def test_calibrate_falls_back_to_ntp(self, ws_auth):
        """不带发起端时间戳时走 NTP：成功要能说清来源，失败要给出原因。"""
        resp = await ws_auth.request(
            {"type": "system_time_calibrate", "locale": "zh-CN"},
            "system_time_calibrate_response",
            timeout=CALIBRATE_TIMEOUT,
        )
        assert resp.get("source") == "ntp"
        assert "mcuSynced" in resp

        if resp.get("success"):
            # 成功必须能说清"从哪台服务器校的、差了多少"，否则无法区分真校准与假成功
            assert resp.get("server"), "校准成功但未返回 NTP 服务器"
            assert isinstance(resp.get("offsetMs"), (int, float))
            data = resp.get("data") or {}
            assert 2024 <= (data.get("year") or 0) <= 2100
        else:
            # 失败必须给出原因（无外网现场应当明确报失败，而不是绿色成功）
            assert resp.get("error")


async def _get_time(ws) -> dict:
    resp = await ws.request({"type": "system_time_get"}, "system_time_get_response")
    assert resp.get("success") is True
    return resp.get("data") or {}


async def _set_timezone(ws, tz: str) -> dict:
    return await ws.request(
        {"type": "system_timezone_set", "timezone": tz},
        "system_timezone_set_response",
        timeout=15.0,
    )


async def _set_sync_mode(ws, mode: str) -> dict:
    return await ws.request(
        {"type": "system_time_sync_mode_set", "mode": mode},
        "system_time_sync_mode_set_response",
    )


@pytest.fixture
async def restore_time_config(ws_auth):
    """用例会改时区和同步模式，结束后恢复原值。"""
    before = await _get_time(ws_auth)
    yield before
    if before.get("timezoneId"):
        await _set_timezone(ws_auth, before["timezoneId"])
    if before.get("syncMode") in ("manual", "auto"):
        await _set_sync_mode(ws_auth, before["syncMode"])


class TestTimezoneAndSyncMode:
    async def test_get_reports_timezone_and_mode(self, ws_auth):
        data = await _get_time(ws_auth)
        assert isinstance(data.get("timezoneId"), str)
        assert isinstance(data.get("utcOffsetMinutes"), int)
        assert -12 * 60 <= data["utcOffsetMinutes"] <= 14 * 60
        assert data.get("syncMode") in ("manual", "auto")

    @pytest.mark.parametrize("bad", ["Mars/Olympus", "../../etc/passwd", "Europe/Berlin;reboot", ""])
    async def test_set_timezone_rejects_invalid(self, ws_auth, bad):
        resp = await _set_timezone(ws_auth, bad)
        assert resp.get("success") is False
        assert resp.get("error")

    async def test_set_timezone_berlin(self, ws_auth, restore_time_config):
        """切到 Europe/Berlin：绝对时刻不变，本地墙钟与偏移按柏林时区（含夏令时）计算。"""
        resp = await _set_timezone(ws_auth, "Europe/Berlin")
        assert resp.get("success") is True, resp.get("error")
        assert "mcuSynced" in resp

        data = await _get_time(ws_auth)
        assert data.get("timezoneId") == "Europe/Berlin"

        device_instant = datetime.fromtimestamp(data["timestamp"] / 1000, tz=timezone.utc)
        expected_offset = int(
            device_instant.astimezone(ZoneInfo("Europe/Berlin")).utcoffset().total_seconds() // 60
        )
        assert data["utcOffsetMinutes"] == expected_offset

        # 换时区不能让绝对时间跳变
        before_ms = restore_time_config["timestamp"]
        assert abs(data["timestamp"] - before_ms) < 60_000

        # 返回的年月日时分要和"UTC 时刻 + 柏林偏移"一致
        local = device_instant.astimezone(ZoneInfo("Europe/Berlin")).replace(tzinfo=None)
        reported = datetime(
            data["year"], data["month"], data["day"], data["hour"], data["minute"], data["second"]
        )
        assert abs((reported - local).total_seconds()) < 2

    async def test_sync_mode_roundtrip(self, ws_auth, restore_time_config):
        resp = await _set_sync_mode(ws_auth, "auto")
        assert resp.get("success") is True
        assert resp.get("mode") == "auto"
        assert (await _get_time(ws_auth)).get("syncMode") == "auto"

        resp = await _set_sync_mode(ws_auth, "manual")
        assert resp.get("success") is True
        assert (await _get_time(ws_auth)).get("syncMode") == "manual"

    async def test_sync_mode_rejects_invalid(self, ws_auth):
        resp = await _set_sync_mode(ws_auth, "sometimes")
        assert resp.get("success") is False

    async def test_manual_set_switches_to_manual_mode(self, ws_auth, restore_time_config):
        """手动设时后必须切回手动模式，否则后台授时会把时间改回去。"""
        assert (await _set_sync_mode(ws_auth, "auto")).get("success") is True

        # 用设备当前本地时间重设一遍，不扰动时钟
        now = await _get_time(ws_auth)
        resp = await ws_auth.request(
            {
                "type": "system_time_set",
                "data": {k: now[k] for k in ("year", "month", "day", "hour", "minute", "second")},
            },
            "system_time_set_response",
            timeout=15.0,
        )
        assert resp.get("success") is True, resp.get("error")
        assert (await _get_time(ws_auth)).get("syncMode") == "manual"

        # 把亚秒误差校回来
        await ws_auth.request(
            {"type": "system_time_calibrate", "clientEpochMs": int(time.time() * 1000)},
            "system_time_calibrate_response",
            timeout=CALIBRATE_TIMEOUT,
        )

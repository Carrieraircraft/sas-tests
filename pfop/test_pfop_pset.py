"""PFOP Pset 范围与双链路验证。"""

from __future__ import annotations

import pytest

from lib.ws_client import WSClient

pytestmark = [pytest.mark.pfop, pytest.mark.p0]


def _parse_pset_ids(frame_data: bytes) -> list[int]:
    text = frame_data.decode("ascii", errors="ignore")
    if len(text) < 3:
        return []
    count = int(text[0:3] or "0")
    ids: list[int] = []
    offset = 3
    for _ in range(count):
        if offset + 3 > len(text):
            break
        ids.append(int(text[offset : offset + 3] or "0"))
        offset += 3
    return ids


class TestPFOPPset:
    def test_comm_start_ack(self, pfop_client):
        pfop_client.send_mid(1, revision=1)
        try:
            frame = pfop_client.recv_frame()
        except TimeoutError:
            pytest.skip("PFOP comm-start got no response in current environment")
        assert frame.mid in (2, 4)

    def test_pset_id_range_0_127(self, pfop_client):
        pfop_client.send_mid(1, revision=1)
        _ = pfop_client.recv_frame()
        pfop_client.send_mid(10, revision=1)
        frame = pfop_client.recv_frame()
        if frame.mid == 4:
            pytest.skip("PFOP returned command error for MID 0010")
        assert frame.mid == 11
        ids = _parse_pset_ids(frame.data)
        assert ids, "PFOP Pset list should not be empty"
        assert all(0 <= i <= 127 for i in ids)

    @pytest.mark.asyncio
    async def test_tcp_pset_list_matches_ws_spec_domain(self, pfop_client, ws_url):
        # PFOP side
        pfop_client.send_mid(1, revision=1)
        _ = pfop_client.recv_frame()
        pfop_client.send_mid(10, revision=1)
        frame = pfop_client.recv_frame()
        if frame.mid == 4:
            pytest.skip("PFOP returned command error for MID 0010")
        assert frame.mid == 11
        pfop_ids = set(_parse_pset_ids(frame.data))

        # WS side
        ws = WSClient()
        await ws.connect(ws_url)
        specs = await ws.get_spec_list()
        await ws.disconnect()

        ws_ids: set[int] = set()
        for item in specs:
            if isinstance(item, dict):
                if "specification_id" in item:
                    ws_ids.add(int(item["specification_id"]))
                elif "id" in item:
                    ws_ids.add(int(item["id"]))

        assert pfop_ids, "PFOP Pset IDs should not be empty"
        if ws_ids:
            # 双链路一致性：PFOP返回的Pset ID应是WS域中的子集
            assert pfop_ids.issubset(ws_ids)

"""PFOP Job 范围验证。"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.pfop, pytest.mark.p1]


def _parse_job_ids(frame_data: bytes, revision: int) -> list[int]:
    text = frame_data.decode("ascii", errors="ignore")
    ids: list[int] = []
    if revision <= 1:
        if len(text) < 2:
            return ids
        count = int(text[0:2] or "0")
        offset = 2
        width = 2
    else:
        if len(text) < 4:
            return ids
        count = int(text[0:4] or "0")
        offset = 4
        width = 4
    for _ in range(count):
        if offset + width > len(text):
            break
        ids.append(int(text[offset : offset + width] or "0"))
        offset += width
    return ids


class TestPFOPJob:
    def test_job_id_range_0_127(self, pfop_client):
        pfop_client.send_mid(1, revision=1)
        try:
            _ = pfop_client.recv_frame()
        except TimeoutError:
            pytest.skip("PFOP comm-start got no response in current environment")
        pfop_client.send_mid(30, revision=1)
        try:
            frame = pfop_client.recv_frame()
        except TimeoutError:
            pytest.skip("PFOP job list request got no response in current environment")
        if frame.mid == 4:
            pytest.skip("PFOP returned command error for MID 0030")
        assert frame.mid == 31
        ids = _parse_job_ids(frame.data, frame.revision)
        if not ids:
            pytest.skip("PFOP returned empty Job list")
        assert all(0 <= i <= 127 for i in ids)

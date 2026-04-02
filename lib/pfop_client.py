"""Minimal PFOP TCP client for integration tests."""

from __future__ import annotations

import socket
from dataclasses import dataclass


@dataclass
class PFOPFrame:
    length: int
    mid: int
    revision: int
    raw: bytes
    data: bytes


class PFOPClient:
    """Tiny PFOP ASCII client (header + data + NUL)."""

    def __init__(self, host: str, port: int, timeout: float = 3.0):
        self._host = host
        self._port = port
        self._timeout = timeout
        self._sock: socket.socket | None = None

    def connect(self) -> None:
        self._sock = socket.create_connection((self._host, self._port), timeout=self._timeout)
        self._sock.settimeout(self._timeout)

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def __enter__(self) -> "PFOPClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def send_mid(self, mid: int, revision: int = 1, data: str = "") -> None:
        """Send a raw PFOP frame with default blank flags/ids."""
        if self._sock is None:
            raise RuntimeError("PFOP socket is not connected")
        data_bytes = data.encode("ascii")
        length = 20 + len(data_bytes)
        header = f"{length:04d}{mid:04d}{revision:03d}" + " " * 9
        payload = header.encode("ascii") + data_bytes + b"\0"
        self._sock.sendall(payload)

    def recv_frame(self) -> PFOPFrame:
        if self._sock is None:
            raise RuntimeError("PFOP socket is not connected")
        buf = bytearray()
        while True:
            chunk = self._sock.recv(4096)
            if not chunk:
                break
            buf.extend(chunk)
            if b"\0" in chunk:
                break
        if not buf or b"\0" not in buf:
            raise TimeoutError("PFOP response not terminated with NUL")
        end = buf.index(0)
        raw = bytes(buf[: end + 1])
        body = raw[:-1]
        if len(body) < 20:
            raise ValueError("PFOP response shorter than header size")
        length = int(body[0:4].decode("ascii", errors="ignore") or "0")
        mid = int(body[4:8].decode("ascii", errors="ignore") or "0")
        rev_text = body[8:11].decode("ascii", errors="ignore").strip()
        revision = int(rev_text) if rev_text else 0
        data = body[20:]
        return PFOPFrame(length=length, mid=mid, revision=revision, raw=raw, data=data)


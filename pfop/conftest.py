"""pfop suite fixtures."""

from __future__ import annotations

import asyncio
from urllib.parse import urlparse

import pytest

from lib.pfop_client import PFOPClient
from lib.ws_client import WSClient


def _host_from_ws_url(ws_url: str) -> str:
    parsed = urlparse(ws_url)
    return parsed.hostname or "127.0.0.1"


@pytest.fixture(scope="module")
async def pfop_env(ws_url):
    """Ensure PFOP protocol is enabled for this suite; restore when done."""
    ws = WSClient()
    await ws.connect(ws_url)
    original = await ws.request({"type": "pfop_config_query"}, "pfop_config_query_response")
    if not original.get("success"):
        await ws.disconnect()
        pytest.skip(f"pfop_config_query unavailable: {original.get('error')}")

    data = dict(original.get("data", {}))
    if "portNumber" not in data:
        await ws.disconnect()
        pytest.skip("pfop_config_query has no portNumber")

    changed = False
    if not bool(data.get("enableProtocol", False)):
        enable_payload = dict(data)
        enable_payload["enableProtocol"] = True
        set_resp = await ws.request(
            {"type": "pfop_config_set", **enable_payload},
            "pfop_config_set_response",
        )
        if not set_resp.get("success"):
            await ws.disconnect()
            pytest.skip(f"cannot enable PFOP protocol: {set_resp.get('error')}")
        changed = True
        await asyncio.sleep(0.5)
        latest = await ws.request({"type": "pfop_config_query"}, "pfop_config_query_response")
        if latest.get("success"):
            data = dict(latest.get("data", data))

    env = {
        "host": _host_from_ws_url(ws_url),
        "port": int(data["portNumber"]),
        "ws_url": ws_url,
        "original": original.get("data", {}),
        "changed": changed,
    }
    yield env

    if changed:
        restore_payload = dict(original.get("data", {}))
        try:
            await ws.request(
                {"type": "pfop_config_set", **restore_payload},
                "pfop_config_set_response",
            )
        except Exception:
            pass
    await ws.disconnect()


@pytest.fixture(scope="function")
def pfop_client(pfop_env):
    c = PFOPClient(pfop_env["host"], pfop_env["port"], timeout=4.0)
    try:
        c.connect()
    except OSError as exc:
        pytest.skip(f"cannot connect PFOP TCP endpoint {pfop_env['host']}:{pfop_env['port']}: {exc}")
    yield c
    c.close()


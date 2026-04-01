"""SAS 自动化测试框架 —— 全局 conftest"""

import asyncio
import logging

import pytest

from lib.ws_client import WSClient
from lib.ssh_utils import RemoteBackend
from lib.log_collector import LogCollector
from lib.db_isolation import DatabaseIsolation
from lib.constants import DEFAULT_WS_URL

logger = logging.getLogger(__name__)


# ── 命令行参数 ──────────────────────────────────────────────────


def pytest_addoption(parser):
    parser.addoption(
        "--ws-url",
        default=DEFAULT_WS_URL,
        help="WebSocket URL of the SAS backend (default: %(default)s)",
    )
    parser.addoption("--ssh-host", default=None, help="SSH host for remote backend")
    parser.addoption("--ssh-user", default="pi", help="SSH user (default: %(default)s)")
    parser.addoption("--ssh-password", default=None, help="SSH password")
    parser.addoption("--ssh-key", default=None, help="Path to SSH private key file")


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def ws_url(request):
    return request.config.getoption("--ws-url")


@pytest.fixture(scope="function")
async def ws(ws_url):
    client = WSClient()
    await client.connect(ws_url)
    yield client
    await client.disconnect()


@pytest.fixture(scope="function")
async def ws_pair(ws_url):
    """两个独立的 WebSocket 客户端，用于并发 / 多客户端测试"""
    a, b = WSClient(), WSClient()
    await a.connect(ws_url)
    await b.connect(ws_url)
    yield a, b
    await b.disconnect()
    await a.disconnect()


@pytest.fixture(scope="session")
def remote(request):
    host = request.config.getoption("--ssh-host")
    if host is None:
        pytest.skip("--ssh-host not provided, skipping SSH-dependent test")
    backend = RemoteBackend(
        host=host,
        user=request.config.getoption("--ssh-user"),
        password=request.config.getoption("--ssh-password"),
        key_filename=request.config.getoption("--ssh-key"),
    )
    yield backend
    backend.close()


@pytest.fixture(scope="session")
def log_collector(remote):
    return LogCollector(remote)


@pytest.fixture(scope="function")
async def db_isolation(remote, ws_url):
    iso = DatabaseIsolation(remote)
    await iso.snapshot()
    yield iso
    await iso.restore()


# ── Hooks ───────────────────────────────────────────────────────


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()

    if report.when != "call" or not report.failed:
        return

    ssh_host = item.config.getoption("--ssh-host", default=None)
    if ssh_host is None:
        return

    try:
        backend = RemoteBackend(
            host=ssh_host,
            user=item.config.getoption("--ssh-user"),
            password=item.config.getoption("--ssh-password"),
            key_filename=item.config.getoption("--ssh-key"),
        )
        loop = asyncio.get_event_loop()
        log_text = loop.run_until_complete(backend.get_backend_log(lines=50))
        backend.close()
    except Exception as exc:
        log_text = f"[conftest] Failed to capture backend log: {exc}"

    item._backend_log = log_text
    logger.info("Captured backend log for failed test %s", item.nodeid)


def pytest_html_results_table_row(report, cells):
    """将后端日志附加到 pytest-html 报告（需要 pytest-html 插件）"""
    try:
        from pytest_html import extras as _  # noqa: F401
    except ImportError:
        return

    backend_log = getattr(report, "_backend_log", None)
    if backend_log:
        cells.append(f"<td><pre>{backend_log}</pre></td>")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    yield
    backend_log = getattr(item, "_backend_log", None)
    if backend_log is not None:
        for report in getattr(item, "_report_sections", []):
            pass
        item.user_properties.append(("backend_log", backend_log))

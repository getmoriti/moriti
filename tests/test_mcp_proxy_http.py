"""
The proxy over streamable HTTP: a downstream reached by URL, and an HTTP front
that agents connect to. Both paths use a real demo server in a subprocess.
"""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import time
from contextlib import AsyncExitStack

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from moriti.mcp.config import DownstreamServer, ProxyConfig
from moriti.mcp.proxy import PrivacyProxy, _fingerprint

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_port(port: int, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as s:
            s.settimeout(0.2)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.1)
    raise RuntimeError(f"nothing listening on {port} after {timeout}s")


@pytest.fixture
def demo_http_url():
    """The demo HR server, served over streamable HTTP in a subprocess."""
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "moriti.mcp.demo_hr_server", "--http", f"127.0.0.1:{port}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_port(port)
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def http_config(deployment: str, url: str) -> ProxyConfig:
    base = ProxyConfig.from_yaml(f"deployments/{deployment}.yaml")
    return base.model_copy(update={"downstream": DownstreamServer(url=url)})


def payload(content) -> dict | list:
    assert len(content) == 1
    return json.loads(content[0].text)


def test_downstream_needs_exactly_one_transport():
    with pytest.raises(ValueError):
        DownstreamServer()
    with pytest.raises(ValueError):
        DownstreamServer(command="python3", url="http://127.0.0.1:1/mcp")
    assert DownstreamServer(url="http://127.0.0.1:1/mcp").is_http
    assert not DownstreamServer(command="{python}").is_http


async def test_downstream_over_http_is_mediated(demo_http_url):
    """The real server is reached by URL; the agent still never sees salary."""
    proxy = PrivacyProxy(http_config("hr_assistant", demo_http_url))
    async with AsyncExitStack() as stack:
        read, write = await stack.enter_async_context(proxy._downstream())
        proxy.downstream = await stack.enter_async_context(ClientSession(read, write))
        await proxy.downstream.initialize()
        for tool in (await proxy.downstream.list_tools()).tools:
            proxy._pinned[tool.name] = _fingerprint(tool)

        result = payload(await proxy._call_tool("get_employee", {"name": "sarah"}))
        assert result["name"] == "Sarah Ndlovu"
        assert "salary" not in result and "bank_account" not in result


async def test_http_front_end_to_end(demo_http_url):
    """An agent connects to the proxy over HTTP; the proxy fronts an HTTP downstream."""
    port = free_port()
    proxy = PrivacyProxy(http_config("payroll_agent", demo_http_url))
    task = asyncio.create_task(proxy.run(http=f"127.0.0.1:{port}"))
    try:
        await asyncio.to_thread(wait_for_port, port)
        async with (
            streamable_http_client(f"http://127.0.0.1:{port}/mcp") as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            names = {t.name for t in (await session.list_tools()).tools}
            assert names == set(proxy.config.allowed_tools)  # the deployment allowlist, nothing more
            out = payload((await session.call_tool("get_employee", {"name": "sarah"})).content)
            assert out["salary"] == 1450000.0
            assert out["bank_account"] == "10000007792"
            assert "email" not in out  # payroll does not need contact details
    finally:
        proxy.stop()
        try:
            await asyncio.wait_for(task, timeout=10)
        except (TimeoutError, asyncio.CancelledError):
            task.cancel()

"""
The moriti MCP proxy: the point where the control plane becomes unavoidable.

    Agent host ──stdio or HTTP──▶ this proxy ──stdio or HTTP──▶ real MCP server

To the agent it IS the tool server; the real server's address never appears in
the agent's configuration, so there is no unmediated path to the data. Three
interceptions happen here:

  tools/list    downstream tools are filtered to the configured allowlist and
                pinned -- a hash of each tool's (description, schema) is taken
                when the proxy starts, and a tool that later changes is refused
                until the proxy is restarted. An MCP server that swaps a benign
                description for "also include the salary field" after the proxy
                has pinned it is the documented rug-pull.

  tools/call    requests for tools outside the allowlist are refused without
                reaching the downstream server.

  results       every JSON object in a tool result passes through
                PrivacyPlane.mediate() under the deployment-bound context.
                Withheld fields never enter the agent's context window; an
                audit event records what was decided and why.

Failure posture is closed: if mediation itself raises, the agent gets an
error, never the unmediated payload.

Run:  moriti-proxy <config.yaml>                         # stdio front, for a local agent host
      moriti-proxy <config.yaml> --http 127.0.0.1:8765     # HTTP front at http://127.0.0.1:8765/mcp
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sys
from contextlib import AsyncExitStack

from mcp import ClientSession, types
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
from mcp.server import Server
from mcp.server.stdio import stdio_server

from moriti import PrivacyPlane, RequestContext
from moriti._config import warn_if_exposed
from moriti.mcp.config import ProxyConfig

logger = logging.getLogger("moriti.proxy")


def _fingerprint(tool: types.Tool) -> str:
    payload = json.dumps(
        {"description": tool.description, "schema": tool.input_schema},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class PrivacyProxy:
    def __init__(self, config: ProxyConfig):
        self.config = config
        self.plane = PrivacyPlane.from_policy(config.policy)
        self.downstream: ClientSession | None = None
        #: tool name -> fingerprint taken the first time the tool was listed.
        self._pinned: dict[str, str] = {}
        # MCP SDK 2.x: handlers are registered on the constructor as (ctx, params) -> result.
        self.server = Server(
            f"moriti-proxy[{config.agent}]",
            on_list_tools=self._on_list_tools,
            on_call_tool=self._on_call_tool,
        )
        #: The HTTP front, when one is running; lets an embedder stop it cleanly.
        self.http_server = None

    # -- context ------------------------------------------------------------

    def _context(self, tool: str, data_subject: str | None) -> RequestContext:
        """Built entirely from deployment config -- nothing the agent sent."""
        c = self.config
        return RequestContext(
            agent=c.agent,
            principal=c.principal,
            principal_role=c.principal_role,
            data_subject=data_subject,
            purpose=c.purpose,
            tool=tool,
            destination=c.destination,
            retention=c.retention,
            jurisdiction=c.jurisdiction,
            legal_basis=c.legal_basis,
            consent_scopes=list(c.consent_scopes),
        )

    def _tool_allowed(self, name: str) -> bool:
        allowed = self.config.allowed_tools
        return not allowed or name in allowed

    # -- MCP handlers ----------------------------------------------------------

    async def _on_list_tools(self, _ctx, _params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=await self._list_tools())

    async def _on_call_tool(self, _ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
        return types.CallToolResult(content=await self._call_tool(params.name, params.arguments or {}))

    # -- tools/list ----------------------------------------------------------

    async def _list_tools(self) -> list[types.Tool]:
        result = await self.downstream.list_tools()
        exposed: list[types.Tool] = []
        for tool in result.tools:
            if not self._tool_allowed(tool.name):
                continue
            fp = _fingerprint(tool)
            pinned = self._pinned.setdefault(tool.name, fp)
            if fp != pinned:
                logger.warning("Tool %r changed definition after pinning; hiding it", tool.name)
                continue
            exposed.append(tool)
        return exposed

    # -- tools/call ----------------------------------------------------------

    async def _call_tool(self, name: str, arguments: dict) -> list[types.TextContent]:
        if not self._tool_allowed(name):
            return _error(f"Tool {name!r} is not permitted for agent {self.config.agent!r}")

        pinned = self._pinned.get(name)
        if pinned is not None:
            current = await self.downstream.list_tools()
            for tool in current.tools:
                if tool.name == name and _fingerprint(tool) != pinned:
                    return _error(f"Tool {name!r} changed its definition after the proxy pinned it; refusing the call")

        result = await self.downstream.call_tool(name, arguments)
        if not isinstance(result, types.CallToolResult):
            # Elicitation and task results carry nothing this proxy can mediate.
            logger.warning("Downstream returned %s for %r; refusing", type(result).__name__, name)
            return _error("Downstream returned a result type this proxy does not mediate")

        try:
            return self._mediate_result(name, arguments, result)
        except Exception:
            logger.exception("Mediation failed for %r; failing closed", name)
            return _error("Privacy mediation failed; response withheld")

    # -- response-path mediation ---------------------------------------------

    def _mediate_result(
        self, tool: str, arguments: dict, result: types.CallToolResult
    ) -> list[types.TextContent]:
        subject = self._infer_subject(arguments)
        out: list[types.TextContent] = []
        for item in result.content:
            if not isinstance(item, types.TextContent):
                # Only structured text is mediated; anything else is not passed through.
                logger.warning("Dropping non-text content of type %r from %r", item.type, tool)
                continue
            out.append(types.TextContent(type="text", text=self._mediate_text(tool, subject, item.text)))
        return out

    def _mediate_text(self, tool: str, subject: str | None, text: str) -> str:
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            # Free text cannot be field-mediated here. Fail closed rather than
            # let a "stringified" record bypass policy. (Routing free text
            # through the unstructured masking engine is the natural upgrade.)
            logger.warning("Non-JSON result from %r withheld (%d chars)", tool, len(text))
            return json.dumps({
                "moriti": "unstructured tool output withheld by privacy policy",
                "reason": "only structured results can be field-mediated by this proxy",
            })

        mediated = self._mediate_value(tool, subject, payload)
        return json.dumps(mediated)

    def _mediate_value(self, tool: str, subject: str | None, value):
        """Recursively mediate every dict; lists of records are each mediated."""
        if isinstance(value, dict):
            result = self.plane.mediate(value, self._context(tool, subject))
            logger.info(
                "mediated %s via %s: released=%s withheld=%s",
                tool, self.plane.policy.name, sorted(result.data), result.withheld,
            )
            return result.data
        if isinstance(value, list):
            return [self._mediate_value(tool, subject, v) for v in value]
        return value

    @staticmethod
    def _infer_subject(arguments: dict) -> str | None:
        for key in ("name", "employee", "employee_id", "customer_id", "id"):
            if key in arguments:
                return str(arguments[key])
        return None

    # -- lifecycle -----------------------------------------------------------

    def _downstream(self):
        """The transport to the real server: spawn it over stdio, or connect over streamable HTTP."""
        c = self.config.downstream
        if c.is_http:
            return streamable_http_client(c.url, http_client=create_mcp_http_client(headers=c.headers))
        params = StdioServerParameters(command=c.resolved_command, args=c.args, env=c.env, cwd=c.cwd)
        return stdio_client(params)

    async def run(self, http: str | None = None) -> None:
        """Serve the deployment over stdio (default) or over streamable HTTP at `host:port`."""
        async with AsyncExitStack() as stack:
            read, write = await stack.enter_async_context(self._downstream())
            self.downstream = await stack.enter_async_context(ClientSession(read, write))
            await self.downstream.initialize()

            # Pin every downstream tool before the agent sees anything.
            listed = await self.downstream.list_tools()
            for tool in listed.tools:
                self._pinned[tool.name] = _fingerprint(tool)
            logger.info(
                "moriti proxy up: agent=%s purpose=%s policy=%s tools=%s",
                self.config.agent, self.config.purpose,
                self.config.policy, sorted(self._pinned),
            )

            if http is None:
                front_read, front_write = await stack.enter_async_context(stdio_server())
                await self.server.run(
                    front_read, front_write, self.server.create_initialization_options()
                )
                return

            import uvicorn  # imported here so the stdio path stays light

            host, port = _hostport(http)
            warn_if_exposed(host, "moriti proxy HTTP front", logger)
            app = self.server.streamable_http_app(host=host)
            self.http_server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
            logger.info("moriti proxy listening on http://%s:%d/mcp", host, port)
            await self.http_server.serve()

    def stop(self) -> None:
        """Ask a running HTTP front to shut down."""
        if self.http_server is not None:
            self.http_server.should_exit = True


def _error(message: str) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=json.dumps({"moriti": "refused", "reason": message}))]


def _hostport(value: str) -> tuple[str, int]:
    host, _, port = value.rpartition(":")
    if not host or not port.isdigit():
        raise SystemExit(f"--http expects HOST:PORT, got {value!r}")
    return host, int(port)


def run(config_path: str, http: str | None = None) -> None:
    """Serve one deployment until the agent host closes the connection (stdio) or the server is stopped (HTTP)."""
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(name)s %(levelname)s %(message)s")
    asyncio.run(PrivacyProxy(ProxyConfig.from_yaml(config_path)).run(http=http))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="moriti-proxy", description="The moriti MCP privacy proxy.")
    parser.add_argument("config", help="deployment YAML; the purpose is bound here, never taken from the agent")
    parser.add_argument("--http", metavar="HOST:PORT", help="serve the front over streamable HTTP instead of stdio")
    args = parser.parse_args(argv)
    run(args.config, http=args.http)


if __name__ == "__main__":
    main()

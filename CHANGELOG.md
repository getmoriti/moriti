# Changelog

All notable changes to moriti are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [0.1.0] - Unreleased

The first release: the runtime as an open-source research and engineering
project, deliberately small. The date is set on release day.

### Added

- **Policy engine.** Per-field decisions (allow, deny, mask, redact, tokenise,
  filter, require approval) from an assigned purpose and the full request
  context: agent, human principal and role, data subject, destination,
  retention, jurisdiction, legal basis, consent scopes. Rules propose, guards
  dispose: purpose necessity, consent, legal basis, external transfer and
  retention may only restrict. Obligations travel with released values. Every
  decision carries the rule that proposed it, the guard that restricted it and
  a reason; audit events never contain protected values.
- **Policy packs** `popia_hr_v1` and `popia_customer_v1`, as working YAML.
- **MCP proxy** (`moriti-proxy`): a stdio MCP server in front of any stdio
  MCP server, with purpose bound in the deployment file, tool definitions
  pinned by hash, a per-deployment tool allowlist, response-path mediation of
  every structured result, and fail-closed handling of errors and unstructured
  output. Written against the MCP Python SDK 2.x.
- **IBM ContextForge external plugin**: the same engine as a `tool_post_invoke`
  plugin in transform mode, purpose bound in the plugin config.
- Examples for the engine, the proxy and the plugin; two demo deployments.
- **Audit events record the rule that proposed each decision** (`AuditEvent.matched_rule`). A field decided by the policy default has no entry.
- **A pluggable audit sink**: `moriti.audit.set_sink(fn)` sends events to a store or SIEM instead of the application log; `set_sink(None)` restores the log. A sink that raises does not block the response, and the event falls back to the log.

- **Google ADK plugin** (`moriti.adapters.adk.MoritiPlugin`): purpose-bound mediation of every tool result through ADK's `after_tool_callback`, tool allowlist through `before_tool_callback`, fail-closed. The proxy's deployment files configure it unchanged.
- **Strands Agents hooks** (`moriti.adapters.strands.MoritiHooks`): tool allowlist through `BeforeToolCallEvent.cancel_tool`, per-field mediation of every result through `AfterToolCallEvent.result`, fail-closed.
- **AgentCore Gateway response interceptor** (`moriti.adapters.agentcore.handler`): rewrites `tools/call` results and JSON HTTP bodies per field; other MCP messages pass through. Plain JSON in and out, built to the documented interceptor contract.
- **Microsoft Agent Framework middleware** (`moriti.adapters.agentframework.MoritiFunctionMiddleware`): allowlist before the call via `MiddlewareTermination`, per-field rewrite of `context.result` after; pydantic results dumped and mediated; fail-closed.
- **Mediation service** (`moriti-serve`, `moriti.http`): `mediate()` behind `POST /mediate/<deployment>` for gateways that can only call HTTP (Azure API Management, Kong, Cloudflare, Envoy). Stateless; fail-closed with a 200 refusal so gateway policies never fall back to the original.
- **Streamable HTTP for the proxy**: `downstream.url` reaches an HTTP MCP server; `moriti-proxy <deployment> --http HOST:PORT` serves the front at `/mcp`. The demo server gains `--http` too.
- Shared adapter vocabulary in `moriti.adapters.common` (`DeploymentConfig`, result mediation helpers).
- **Your own policy packs**: `policy:` accepts a file path (resolved next to the deployment file first), a name found in `MORITI_POLICY_PATH`, or a bundled name; user packs win over bundled ones. `PrivacyPlane.from_policy` and `Policy.load` take the same reference.
- **Undefined purposes are denied by default.** A request whose purpose the policy does not define under `purposes` is denied by the `purpose_necessity` guard (`require_known_purpose`, default `true`), so a typo in a deployment cannot read as "nothing to check". A policy that deliberately leaves purposes open sets `require_known_purpose: false`.

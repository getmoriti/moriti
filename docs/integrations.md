---
title: Integrations
description: The MCP proxy, ContextForge, Google ADK, Strands, Microsoft Agent Framework, AgentCore and HTTP gateways.
order: 5
---

# Integrations

One engine and one deployment file sit behind every integration. Choose where mediation should run.

| Where | Install | How it runs | Tested against |
| --- | --- | --- | --- |
| Any MCP client | `moriti[mcp]` | MCP proxy | A real MCP client, over stdio and HTTP |
| IBM ContextForge | `moriti[contextforge]` | External plugin | ContextForge's plugin framework (cpex), not yet a running gateway |
| Google ADK | `moriti[adk]` | Plugin | ADK's own tool classes, not yet a running agent |
| Strands Agents | `moriti[strands]` | Hooks | Strands' own hook registry, not yet a running agent |
| Microsoft Agent Framework | `moriti[agentframework]` | Function middleware | A real tool through the framework's middleware, not yet a running agent |
| Amazon Bedrock AgentCore | none | Gateway response interceptor | The documented event contract, not yet a live gateway |
| Azure API Management, Kong, other HTTP-only gateways | `moriti[serve]` | HTTP service | The service's HTTP API, not yet behind a real gateway |
| Your own code | none | `PrivacyPlane.mediate()` | The engine's own test suite |

All of this runs in CI on every change. None of it has run in a production deployment yet.

## MCP proxy

See the [Quickstart](/docs/quickstart). The proxy speaks stdio for a local agent host and streamable HTTP for everything else. It also refuses tool definitions that change after the proxy has pinned them at startup, filters `tools/list` to `allowed_tools`, and fails closed.

## IBM ContextForge

moriti runs as an external plugin inside [ContextForge](https://github.com/IBM/mcp-context-forge): its own process, called by the gateway on every `tool_post_invoke`, rewriting the result before the gateway builds the agent's response. It needs Python 3.12, a ContextForge requirement.

```bash
pip install "moriti[contextforge]"
```

The gateway passes the hook only the tool name and the result, and has no concept of purpose. So purpose is bound in the plugin's `config` block, with one plugin instance per deployment, scoped with `conditions`. The plugin must run in `mode: transform`: that is what lets the rewritten result reach the agent, and observe-only modes discard it. The package includes `gateway-plugin.example.yaml` and example plugin configs under `moriti/adapters/contextforge/`.

## Google ADK

```bash
pip install "moriti[adk]"
```

```python
from google.adk.runners import Runner
from moriti.adapters.adk import MoritiPlugin

runner = Runner(
    app_name="hr", agent=root_agent, session_service=session_service,
    plugins=[MoritiPlugin.from_yaml("hr_assistant.yaml")],
)
```

The plugin rewrites each tool result in `after_tool_callback` and enforces the tool allowlist in `before_tool_callback`.

## Strands Agents

```bash
pip install "moriti[strands]"
```

```python
from strands import Agent
from moriti.adapters.strands import MoritiHooks

agent = Agent(tools=[get_employee], hooks=[MoritiHooks.from_yaml("hr_assistant.yaml")])
```

## Microsoft Agent Framework

```bash
pip install "moriti[agentframework]"
```

```python
from agent_framework import Agent
from moriti.adapters.agentframework import MoritiFunctionMiddleware

agent = Agent(client=client, tools=[get_employee],
              middleware=[MoritiFunctionMiddleware.from_yaml("hr_assistant.yaml")])
```

## Amazon Bedrock AgentCore

AgentCore Gateway runs a Lambda response interceptor after a target answers and before the agent sees the answer. `moriti.adapters.agentcore.handler` is that function. Package it with moriti and a deployment file, set the handler to `moriti.adapters.agentcore.handler` and `MORITI_DEPLOYMENT` to the deployment file, and attach it to the gateway as a response interceptor. The event is plain JSON in and out, so the function needs no AWS SDK.

> This adapter is built to the interceptor contract in the AgentCore developer guide. It has not yet been exercised on a live gateway.

## Azure API Management, Kong and other HTTP-only gateways

Run the [mediation service](/docs/api#http-mediation-service) and have a gateway policy send it the tool result and substitute what comes back. An illustrative Azure API Management outbound policy:

```text
<outbound>
  <send-request mode="new" response-variable-name="mediated" timeout="10" ignore-error="false">
    <set-url>https://moriti.internal/mediate/hr_assistant</set-url>
    <set-method>POST</set-method>
    <set-header name="Content-Type" exists-action="override"><value>application/json</value></set-header>
    <set-body>@(new JObject(
        new JProperty("tool", context.Request.Url.Path),
        new JProperty("arguments", new JObject()),
        new JProperty("result", JToken.Parse(context.Response.Body.As<string>(preserveContent: true)))).ToString())</set-body>
  </send-request>
  <return-response>
    <set-status code="200" />
    <set-header name="Content-Type" exists-action="override"><value>application/json</value></set-header>
    <set-body>@(((IResponse)context.Variables["mediated"]).Body.As<JObject>()["result"].ToString())</set-body>
  </return-response>
</outbound>
```

## Another gateway

An adapter is a thin wrapper around `PrivacyPlane.mediate()`. See `moriti/adapters/` for the existing ones.

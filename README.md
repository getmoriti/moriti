# moriti

[![ci](https://github.com/getmoriti/moriti/actions/workflows/ci.yml/badge.svg)](https://github.com/getmoriti/moriti/actions/workflows/ci.yml) [![licence: Apache-2.0](https://img.shields.io/badge/licence-Apache--2.0-blue.svg)](LICENSE) [![python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

**The open-source privacy runtime for agentic AI.**

moriti sits between AI agents and enterprise systems and answers one question at runtime:

> Should this particular data be used in this particular way for this particular purpose?

```
Agent
  ↓
moriti
  ↓
MCP / API / RAG / Database
```

Access to data does not automatically mean permission to use all of that data. An HR agent doing a directory lookup may reach the employee record — that does not mean salary should enter its context window.

## What it does

A deterministic policy engine evaluates every data access against its full context — agent identity, human principal, assigned purpose, data subject, destination, retention — and enforces a per-field decision before the data reaches the agent:

```
ALLOW             the field passes through
DENY              the field is omitted entirely
REDACT            replaced by a visible placeholder
MASK              partially obscured (sXXXX@example.com)
TOKENISE          replaced by a stable token (keyed when MORITI_TOKEN_KEY is set)
DETOKENISE        the original, only when a reversible tokeniser is registered
FILTER            the field is dropped
REQUIRE_APPROVAL  withheld until someone approves
```

Withheld values never enter the agent's context, and every decision produces an audit event explaining *why* — without logging the protected values.

### Rules propose, guards dispose

Policies have two layers, and their ordering is the point. **Rules** grant access the familiar way ("the payroll agent may read salary for payroll runs"). **Guards** — purpose necessity, consent compatibility, legal basis, external transfer, retention — run afterwards and may only ever *restrict* the outcome, never loosen it.

That is what separates this from IAM:

```
IAM             → Who are you?
Authorisation   → Can you access this resource?
Agent security  → Can the agent perform this action?
moriti          → Should this data be used this way?
```

A marketing employee with legitimate CRM access requests a customer's mobile number for a fraud investigation, destined for a third-party API. Every access-control layer passes. moriti denies it — the consent on file covers marketing communication only — and the audit event records which guard fired and why.

## Quick start

Python 3.11 or newer. The MCP proxy uses the MCP Python SDK 2.x; the ContextForge plugin needs Python 3.12.

```bash
pip install moriti
```

The [quickstart](https://www.moriti.dev/docs/quickstart) takes it from there. The examples below live in the repository, so they run from a clone:

```bash
git clone https://github.com/getmoriti/moriti && cd moriti
pip install -e ".[dev]"
python -m examples.demo_policy_engine
```

```python
from moriti import PrivacyPlane, RequestContext, Destination, LegalBasis

plane = PrivacyPlane.from_policy("popia_hr_v1")

result = plane.mediate(
    {"name": "Sarah Ndlovu", "email": "sarah@example.co.za", "salary": 1450000},
    RequestContext(
        agent="hr_assistant",
        purpose="employee_directory_lookup",
        destination=Destination.INTERNAL_MODEL,
        legal_basis=LegalBasis.LEGITIMATE_INTEREST,
        requested_fields=["name", "email", "salary"],
    ),
)

result.data       # {'name': 'Sarah Ndlovu', 'email': 'sarah@example.co.za'}
result.withheld   # ['salary'] — not necessary for the assigned purpose
result.audit      # evidence event: decisions, reasons, the guard that fired
```

## The MCP proxy: enforcement you cannot route around

The proxy speaks stdio for a local agent host and streamable HTTP for everything else: a downstream reached by `url:` instead of `command:`, and a front served with `--http HOST:PORT` that agents and cloud gateways connect to at `/mcp`.

A policy engine an agent must volunteer to call is not enforcement. The proxy is an MCP server on the front and an MCP client to the real tool server behind, with mediation on every result in between — the agent's configuration points at the proxy and never learns the downstream address.

```bash
pip install -e ".[mcp]"        # MCP Python SDK 2.x
python -m examples.demo_mcp_proxy
```

Two agents call the same tool on the same downstream server and ask about the same employee:

```
hr_assistant   (purpose: employee_directory_lookup) → name, email, department
payroll_agent  (purpose: monthly_payroll_processing) → name, salary, bank_account
```

**Purpose is bound in the deployment config at provisioning time — never taken from the agent.** An agent that could declare its own purpose would declare whichever one unlocks the data. Binding it at deployment makes purpose organisational configuration: something a privacy officer sets, and the agent cannot vary.

The proxy also pins every downstream tool definition by hash when it starts (a tool that changes its description afterwards is refused until the proxy restarts — the MCP "rug pull"), filters `tools/list` to a per-deployment allowlist, and fails closed: if mediation errors, the agent gets a refusal, never the unmediated payload.

Point Claude Code (or any MCP client) at a deployment via `.mcp.json`:

```json
{
  "mcpServers": {
    "moriti-hr-directory": {
      "command": "python3",
      "args": ["-m", "moriti.mcp.proxy", "deployments/hr_assistant.yaml"]
    }
  }
}
```

## Policies are YAML

```yaml
name: popia_hr
default_decision: deny            # nothing is released unless granted AND guarded
require_legal_basis: true

purposes:
  employee_directory_lookup:
    necessary_fields: [name, email, department, job_title]   # data minimisation

fields:
  salary:
    never_external: true          # whatever a rule says, this never leaves
    no_persistence: true          # and never becomes agent memory

rules:
  - id: directory-contact-fields
    match: { purpose: employee_directory_lookup }
    field: [name, email, department, job_title]
    decision: allow
    reason: contact details are necessary for a directory lookup
```

Two POPIA-oriented packs ship as working examples: `popia_hr_v1` and `popia_customer_v1`.

**Your own packs** never need to touch the installed package. A deployment's `policy:` can be a file path (`./policies/my_bank_v1.yaml`, resolved next to the deployment file first), a bare name found in the directories listed in `MORITI_POLICY_PATH` (separated like `PATH`), or a bundled name. Your packs win over bundled ones, so copying `popia_hr_v1.yaml` into your own directory and editing it is the whole workflow.

## Run inside IBM ContextForge

You don't have to use moriti's own proxy. It also runs as an **external plugin** inside [ContextForge](https://github.com/IBM/mcp-context-forge), IBM's Apache-2.0 MCP gateway — its own process, called by the gateway on every `tool_post_invoke`, rewriting the result before the gateway builds the agent's response. Same engine, same policies, one more front door.

```bash
# Python 3.12 (a ContextForge / cpex requirement)
pip install -e ".[contextforge]"

# 1. start the plugin server for a deployment (purpose is bound in the YAML)
PLUGINS_CONFIG_PATH=moriti/adapters/contextforge/resources/plugins/hr_assistant.yaml \
CHUK_MCP_CONFIG_PATH=moriti/adapters/contextforge/resources/runtime/config.yaml \
PLUGINS_SERVER_PORT=8000 python -m cpex.framework.external.mcp.server.runtime

# 2. register it in the gateway's plugins/config.yaml
#    (see moriti/adapters/contextforge/gateway-plugin.example.yaml)

# 3. call tools through the gateway — withheld fields never reach the agent
python -m examples.demo_contextforge   # offline walkthrough of both deployments
```

Two things worth knowing. The gateway hands the hook only `(tool name, result)` and knows the user and tenant but has **no concept of purpose** — so purpose is bound in the plugin's `config` block, one plugin instance per deployment, scoped with `conditions`. The agent never declares it. And the plugin must run in `mode: transform`: the gateway's own hook policy lists `result` as the writable field for `tool_post_invoke`, which is what lets the per-field rewrite reach the agent; observe-only modes discard it.

## Run inside Google ADK

The same engine runs as an [ADK](https://google.github.io/adk-docs/) plugin. ADK fires `after_tool_callback` after every tool returns, and the dict the plugin hands back is what the agent sees; `before_tool_callback` enforces the deployment's tool allowlist before a tool ever runs.

```bash
pip install -e ".[adk]"
python -m examples.demo_adk
```

```python
from google.adk.runners import Runner
from moriti.adapters.adk import MoritiPlugin

runner = Runner(
    app_name="hr", agent=root_agent, session_service=session_service,
    plugins=[MoritiPlugin.from_yaml("deployments/hr_assistant.yaml")],
)
```

One deployment file configures the proxy, the ContextForge plugin and the ADK plugin alike. The purpose is bound in that file, and neither the model nor the tool arguments can change it.

## Run inside Amazon Bedrock AgentCore

AgentCore Gateway runs a Lambda *response interceptor* after a target answers and before the agent sees the answer. `moriti.adapters.agentcore.handler` is that function. It rewrites `tools/call` results per field under the deployment's purpose and passes every other message through. AgentCore's own Cedar policy decides who may call which tool, and Guardrails flags sensitive value types; this decides whether the field should be in the answer at all.

```bash
# Package the function with moriti and a deployment file, then set:
#   handler:  moriti.adapters.agentcore.handler
#   MORITI_DEPLOYMENT=deployments/hr_assistant.yaml
# and attach it to the gateway as a RESPONSE interceptor.
```

The event is plain JSON in and out, so no AWS SDK is needed inside the function and the tests run without an account. Built against the interceptor contract in the AgentCore developer guide; not yet exercised on a live gateway.

## Run inside Strands Agents

Strands fires hooks around every tool call: `cancel_tool` on the before event stops a tool from running, and `result` on the after event is what the model sees.

```bash
pip install -e ".[strands]"
python -m examples.demo_strands
```

```python
from strands import Agent
from moriti.adapters.strands import MoritiHooks

agent = Agent(tools=[get_employee], hooks=[MoritiHooks.from_yaml("deployments/hr_assistant.yaml")])
```

## Run inside Microsoft Agent Framework

Every tool call passes through the agent's function middleware. Before the call the middleware enforces the deployment's allowlist by raising the framework's own `MiddlewareTermination` with a refusal; after it, `context.result` is rewritten per field.

```bash
pip install -e ".[agentframework]"
python -m examples.demo_agentframework
```

```python
from agent_framework import Agent
from moriti.adapters.agentframework import MoritiFunctionMiddleware

agent = Agent(client=client, tools=[get_employee],
              middleware=[MoritiFunctionMiddleware.from_yaml("deployments/hr_assistant.yaml")])
```

## Behind Azure API Management, Kong, or any gateway that can only call HTTP

Some gateways cannot run Python in the data path. The mediation service puts `mediate()` behind one endpoint, so a gateway policy hands it the tool result and substitutes what comes back. It holds no data and no state.

```bash
pip install -e ".[serve]"
moriti-serve deployments/hr_assistant.yaml deployments/payroll_agent.yaml --http 127.0.0.1:8770

curl -s localhost:8770/mediate/hr_assistant -H 'content-type: application/json' \
  -d '{"tool": "get_employee", "arguments": {"name": "sarah"}, "result": {"name": "Sarah Ndlovu", "salary": 1450000}}'
# {"result": {"name": "Sarah Ndlovu"}, "withheld": ["salary"], "deployment": "hr_assistant", ...}
```

The service has no authentication of its own, and neither does the proxy's HTTP front. Keep them on loopback or a private network, or put them behind a gateway that authenticates callers; both log a warning when bound to any other address.

An illustrative Azure API Management outbound policy: call the service with the backend response, return its `result` instead.

```xml
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

A mediation error comes back as HTTP 200 with a refusal in `result` and `"error": "mediation_failed"`, on purpose: a 5xx tempts a gateway policy into passing the original response through.

Adding another gateway is a thin adapter around the same `mediate()` call — see `moriti/adapters/`.

## What stays open

This runtime is Apache-2.0, and every released version stays that way. The licence is irrevocable, so if the project ever changed course you could fork it, and that is by design.

- **Privacy enforcement will never be gated, degraded or rate-limited to push anyone toward paying.** The parts that touch data are the open parts: the decision engine, the guards, the policy packs, the masking, the proxy and the gateway adapters. Anyone can read exactly what happens to a field.
- **No telemetry, no phone-home.** The runtime makes no network calls of its own, and never will.
- **If a business ever exists around moriti, it will be operations and support around the runtime, not the runtime.** Fleet policy management, org-wide audit retention, evidence, service levels. None of it touches a single field's decision.
- **If maintenance ever stops, the code goes to a neutral home, not an archive.**

Ethyca's Fides, an open-source privacy engineering platform, was archived in August 2026, and Ethyca's current product, Astralis, is proprietary. Other open-source projects cover adjacent ground: agent-governance policy engines, MCP gateways and PII redaction. What moriti adds is the decision about personal data itself: purpose, consent, lawful basis and destination, per field, in the path of the agent. It is open, and it stays that way.

> a runtime you can read, run in your own cloud, and fix yourself is not a business model. it is the point.
>
> from the [project philosophy](https://www.moriti.dev/philosophy)

## Principles

- **Deterministic.** No LLM makes or influences an access decision.
- **Fails closed.** Enforcement errors redact; mediation errors refuse; unstructured output is withheld rather than guessed at.
- **Privacy-safe logs.** No field value is ever written to a log or audit event — by the engine, the maskers, or the proxy. An audit event can carry a data-subject reference, which is personal data, so send events to a store you control.
- **Self-hostable.** No cloud, no account, no phone-home. This runtime is genuinely useful on its own, deliberately.
- **Explainable.** Every decision carries the rule that proposed it, the guard that restricted it, and a human-readable reason.
- **Integrate, don't rebuild.** IAM, OAuth, Cerbos/OpenFGA/OPA, DLP and agent frameworks all keep their jobs. moriti adds the layer they structurally cannot express: purpose.

## Status

An open-source research and engineering project exploring runtime privacy enforcement for autonomous software — not yet an enterprise platform. The v0.1 surface is deliberately small.

**The policy packs are examples.** They show how the engine expresses purpose, consent and legal basis. They are not legal advice and not a compliance certification: have your own counsel review any policy before relying on it.

**Shipped in v0.1:** the policy engine and its five guards, two POPIA packs, the MCP proxy (stdio and streamable HTTP), the IBM ContextForge plugin, the Google ADK plugin, Strands Agents hooks, Microsoft Agent Framework middleware, an AgentCore Gateway response interceptor built to the documented contract, and the mediation service for HTTP-only gateways.

**Planned next:** an agentgateway adapter; OPA, Cerbos and OpenFGA verdicts as inputs; an NDPA pack; mediation of unstructured tool output; evidence export.

Under active investigation:

- purpose provenance — who declares why an agent needs data, and when that can be trusted
- agent memory — permission to *use* data versus permission to *retain* it
- agent-to-agent transfer — restrictions that follow the data
- destination rules — per model, vendor and jurisdiction
- evidence — proving after the fact why every sensitive-data use was permitted

## Contributing and security

Bugs and ideas go in Issues; questions and show-and-tell in Discussions. [CONTRIBUTING.md](CONTRIBUTING.md) has the setup, the rules a change must keep, and the DCO sign-off. [SECURITY.md](SECURITY.md) says how to report a vulnerability privately. If you run moriti and are willing to say so, add yourself to [ADOPTERS.md](ADOPTERS.md).

## Licence

Apache-2.0. Privacy infrastructure should be inspectable and accessible before an organisation can afford enterprise privacy software.

The licence covers the code. The moriti name and logo are not covered: please don't use them to imply endorsement, or as the name of a fork.

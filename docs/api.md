---
title: API reference
description: The Python API and the HTTP mediation service.
order: 4
---

# API reference

## Python

```python
from moriti import (
    PrivacyPlane, RequestContext, Destination, Retention, LegalBasis,
    Decision, Obligation, Policy, PolicyEngine,
)
```

### `PrivacyPlane`

```python
plane = PrivacyPlane.from_policy("popia_hr_v1")   # a file path, a name on MORITI_POLICY_PATH, or a bundled pack
```

**`plane.mediate(record, ctx, audit=True) -> MediationResult`** evaluates the request, enforces the outcome on `record` and emits an audit event. If `ctx.requested_fields` is empty, the whole record counts as requested, so wrapping an existing tool response needs no other change.

**`plane.decide(ctx) -> list[FieldDecision]`** evaluates without touching data. Use it to check a tool call before running it.

### `MediationResult`

| Member | Meaning |
| --- | --- |
| `data` | What the agent may receive. |
| `decisions` | A `FieldDecision` per requested field. |
| `audit` | The `AuditEvent`, or `None` if `audit=False`. |
| `withheld` | Names of fields the agent did not receive a usable value for. |
| `explain()` | A human-readable rationale. |

### `FieldDecision`

`field`, `decision`, `reason`, `obligations`, `matched_rule` and `restricted_by`, the guards that restricted the rule's proposal, in the order they fired.

### `RequestContext`

`agent` and `purpose` are required. Everything else is optional: `principal`, `principal_role`, `data_subject`, `resource`, `requested_fields`, `task`, `tool`, `destination`, `jurisdiction`, `retention`, `legal_basis`, `consent_scopes`. See [Concepts](/docs/concepts) for the values.

### Tokenisation

The default tokeniser is deterministic, so it needs no infrastructure. Set `MORITI_TOKEN_KEY` and it is HMAC-SHA256 under that key: a token cannot be recovered by hashing guesses without the key. Without the key it is a plain SHA-256, which is stable but can be reversed for low-entropy values such as ID numbers and account numbers, and a warning is logged once. Treat that as a development default. For real use, set the key or register a vault:

```python
from moriti import enforcement
enforcement.set_tokeniser(vault.tokenise, vault.detokenise)
```

`detokenise` decisions are redacted until a reversible tokeniser is registered.

### Audit events

```json
{
  "event_id": "…",
  "timestamp": "2026-10-03T10:24:12Z",
  "agent": "hr_assistant",
  "purpose": "employee_directory_lookup",
  "policy": "popia_hr_v1",
  "decisions": { "name": "allow", "salary": "deny" },
  "reasons": { "name": "…", "salary": "…" },
  "matched_rule": { "name": "directory-contact-fields" },
  "restricted_by": { "salary": ["purpose_necessity"] }
}
```

Events never contain field values. They do carry `data_subject` when the deployment or the tool arguments supply a reference, and that reference is personal data in its own right, so send events to a store you control. `matched_rule` has no entry for a field decided by the policy default.

By default events are written to the `moriti.audit` logger. To send them elsewhere, register a sink once:

```python
from moriti import audit
audit.set_sink(siem.send)    # audit.set_sink(None) restores the log
```

A sink that raises does not block the response. The failure is logged and the event falls back to the log, so it is not lost.

## HTTP mediation service

For gateways that cannot run Python in the data path, such as Azure API Management, Kong or an Envoy filter.

```bash
pip install "moriti[serve]"
moriti-serve hr_assistant.yaml payroll_agent.yaml --http 127.0.0.1:8770
```

Each file is served as `/mediate/<file stem>`. Purpose is bound in the file; nothing in a request can change it. The service holds no data and keeps no state, so several can run behind a load balancer.

The service has no authentication of its own. Keep it on loopback or a private network, or put it behind a gateway that authenticates callers. It logs a warning when it is bound to any other address.

### `POST /mediate/{deployment}`

Request:

```json
{
  "tool": "get_employee",
  "arguments": { "name": "sarah" },
  "result": { "name": "Sarah Ndlovu", "salary": 1450000 }
}
```

Response:

```json
{
  "result": { "name": "Sarah Ndlovu" },
  "withheld": ["salary"],
  "deployment": "hr_assistant",
  "agent": "hr_assistant",
  "purpose": "employee_directory_lookup",
  "policy": "popia_hr_v1"
}
```

`result` can be any JSON value. An object is mediated as a record, field by field; a list is mediated element by element; a string is parsed as JSON and mediated the same way, and a string that is not JSON is withheld, because free text cannot be mediated per field. Other scalars pass through. `POST /mediate` works when exactly one deployment is loaded.

### Other routes

| Route | Returns |
| --- | --- |
| `GET /healthz` | `{"status": "ok", "deployments": [...]}` |
| `GET /deployments` | Each loaded deployment and the purpose bound to it. |

### Errors

A mediation failure returns HTTP **200** with a refusal in `result` and `"error": "mediation_failed"`. This is deliberate: a 5xx tempts a gateway policy into passing the original response through. A malformed body is 400. An unknown deployment is 404.

## The proxy

```bash
moriti-proxy deployment.yaml                  # stdio, for a local agent host
moriti-proxy deployment.yaml --http HOST:PORT # streamable HTTP, served at /mcp
```

The proxy is an MCP server to the agent and an MCP client to the real server. It filters `tools/list` to `allowed_tools`, mediates every result, pins each downstream tool definition by hash when it starts so that a tool that changes its description afterwards is refused until the proxy restarts, and fails closed.

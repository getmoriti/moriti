---
title: Quickstart
description: Install moriti, make one decision, then put it in the path of an agent.
order: 1
---

# Quickstart

moriti decides, field by field, what an agent may receive for its assigned purpose. This page shows how to enforce that decision before a tool result reaches the agent.

## Install

Python 3.11 or newer.

```bash
pip install moriti
```

The core has two dependencies. Each integration is an extra: `moriti[mcp]` for the proxy, `moriti[serve]` for the HTTP service, and others listed under [Integrations](/docs/integrations).

## Make a decision

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

print(result.data)      # {'name': 'Sarah Ndlovu', 'email': 'sarah@example.co.za'}
print(result.withheld)  # ['salary']
print(result.explain()) # the reason and the guard for every field
```

`popia_hr_v1` is a policy pack that ships with the package. A directory lookup needs contact details, so salary never leaves `mediate()`. The decision involves no model: the same data, context and policy always produce the same result.

## Put it in the path of an agent

An engine the agent has to volunteer to call is not enforcement. The MCP proxy sits between the agent and the downstream tool server, so every result is mediated before the agent sees it. Mediation covers what passes through the proxy, so the agent must have no other route to the same data.

```bash
pip install "moriti[mcp]"
```

Describe the deployment. The package includes a small HR MCP server, so you can run this without building a tool server of your own. The purpose comes from this file, which whoever provisions the agent controls. The agent cannot declare or change it.

```yaml
# hr_assistant.yaml
agent: hr_assistant
purpose: employee_directory_lookup
policy: popia_hr_v1
legal_basis: legitimate_interest
allowed_tools: [get_employee, list_employees]
downstream:
  command: "{python}"                    # the HR server that ships with the package
  args: [-m, moriti.mcp.demo_hr_server]
```

Point the agent at the proxy. This is the configuration for Claude Code (`.mcp.json`); other MCP clients take the same command and arguments in their own format. `moriti-proxy` has to be on the `PATH` of the process that launches it, so if you installed into a virtual environment, use the full path to it.

```json
{
  "mcpServers": {
    "moriti-hr": {
      "command": "moriti-proxy",
      "args": ["hr_assistant.yaml"]
    }
  }
}
```

Ask the agent: *Look up Sarah Ndlovu in the employee directory.* The downstream server returns the whole record; the agent receives:

```json
{
  "name": "Sarah Ndlovu",
  "email": "sarah.ndlovu@example.co.za",
  "department": "Engineering",
  "job_title": "Staff Engineer"
}
```

Employee ID, salary, bank account and tax number are withheld from the tool response before it reaches the agent. A directory lookup needs to reach someone. It has no use for what they earn.

To use your own tool server, replace `downstream` with its command, or with `url:` for a server that speaks streamable HTTP.

## Next

- [Concepts](/docs/concepts): purpose, guards and decisions.
- [Policies](/docs/policies): write your own pack.
- [Integrations](/docs/integrations): ContextForge, Google ADK, Strands, Microsoft Agent Framework, AgentCore, and any gateway that can call HTTP.

---
title: Quickstart
description: Install moriti, make one decision, then put it between an agent and its tools.
order: 1
---

# Quickstart

moriti decides, field by field, what an agent may receive for its assigned purpose. This page shows how to enforce it before a tool result reaches the agent.

## Install

Python 3.11 or newer.

```bash
pip install moriti
```

The core has two dependencies. Integrations are optional extras: `moriti[mcp]` for the proxy, `moriti[serve]` for the HTTP service, and others under [Integrations](/docs/integrations).

## Make a decision

Save this as `quickstart.py`:

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

print(result.data)
print(result.withheld)
print(result.explain())
```

Run it with `python quickstart.py`. You should see:

```text
{'name': 'Sarah Ndlovu', 'email': 'sarah@example.co.za'}
['salary']
  name: ALLOW
      contact details are necessary for a directory lookup
  email: ALLOW
      contact details are necessary for a directory lookup
  salary: DENY  (restricted by purpose_necessity)
      'salary' is not necessary for the assigned purpose 'employee_directory_lookup'
```

`popia_hr_v1` is a policy pack that ships with the package, written for South Africa's POPIA. A directory lookup needs contact details, so salary is left out. No LLM is involved: the same data, context and policy always give the same result. This call is the engine on its own, and whoever writes the code chooses to run it. The next section puts it where the agent cannot skip it.

## Put it between the agent and its tools

An engine the agent has to volunteer to call is not enforcement. The MCP proxy sits between the agent and the tool server, so every result is mediated before the agent sees it. moriti can only protect what passes through it, so give the agent no other route to the same data.

```bash
pip install "moriti[mcp]"
```

Describe the deployment: one agent, one purpose, one policy. Whoever provisions the agent sets the purpose here. The agent cannot declare or change it.

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

`downstream` is the tool server being protected. This one is a small HR server that ships with the package, so there is nothing to build.

Point the agent at the proxy. For Claude Code, save this as `.mcp.json` in your project; other MCP clients take the same command and arguments in their own format. If moriti is in a virtual environment, use the full path to `moriti-proxy` as the command.

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

Ask the agent: *Look up Sarah Ndlovu in the employee directory.* The downstream server returns the whole record. The agent receives:

```json
{
  "name": "Sarah Ndlovu",
  "email": "sarah.ndlovu@example.co.za",
  "department": "Engineering",
  "job_title": "Staff Engineer"
}
```

Employee ID, salary, bank account and tax number are withheld before the response reaches the agent. A directory lookup needs a name and a way to contact someone. Pay and bank details have no place in it.

To protect your own tool server, replace `downstream` with its command, or with `url:` for a server over HTTP.

## Next

- [Concepts](/docs/concepts): purpose, guards and decisions.
- [Policies](/docs/policies): write your own pack.
- [Integrations](/docs/integrations): ContextForge, Google ADK, Strands, Microsoft Agent Framework, AgentCore, and any gateway that can call HTTP.

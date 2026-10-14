# Testing moriti yourself

Everything here runs on a laptop with no accounts, except the two live-gateway
sections at the end. Python 3.11 or 3.12; the ContextForge extra needs 3.12.

## 1. The suite, the lint, the demos

```bash
git clone https://github.com/getmoriti/moriti.git && cd moriti
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[mcp,adk,strands,agentframework,serve,dev]"        # add ,contextforge on Python 3.12
python -m pytest                               # engine, proxy (stdio + HTTP), ADK, Strands, AgentCore
python -m ruff check .
python -m examples.demo_policy_engine
python -m examples.demo_mcp_proxy
python -m examples.demo_adk
python -m examples.demo_strands
python -m examples.demo_agentframework
python -m examples.demo_contextforge           # 3.12 only
```

If the suite fails with `No module named 'moriti'`, the shell is running
another environment's pytest: conda's base environment has one, and the header
line of the run shows its version rather than the one you just installed. Run
`source .venv/bin/activate` again, check that `which python` prints a path
inside `.venv`, and rerun. `.venv/bin/python -m pytest` always uses the right
one.

## 2. The stranger test: install from the wheel, not the checkout

This is what CI does and what a new user experiences. It catches anything
that only works in editable mode.

```bash
pip install build && python -m build --wheel --outdir dist
python3 -m venv /tmp/fresh && /tmp/fresh/bin/pip install "$(ls dist/moriti-*.whl)[mcp,adk,strands,dev]"
/tmp/fresh/bin/pytest -q -p no:cacheprovider      # the console script, not `python -m pytest`, so the wheel is what runs
```

## 3. The engine by hand

```python
from moriti import PrivacyPlane, RequestContext, Destination, LegalBasis, Retention

plane = PrivacyPlane.from_policy("popia_hr_v1")
record = {"name": "Sarah Ndlovu", "email": "sarah@example.co.za", "salary": 1450000, "bank_account": "10000007792"}

def ask(**ctx):
    r = plane.mediate(record, RequestContext(agent="payroll_agent", principal_role="hr_payroll_admin",
                                             tool="get_employee", **ctx))
    print(sorted(r.data), "withheld:", r.withheld)
    for d in r.decisions:
        print(f"  {d.field:13} {d.decision.value:6} {d.reason}  guards={d.restricted_by}")

ask(purpose="monthly_payroll_processing", destination=Destination.INTERNAL_SYSTEM, legal_basis=LegalBasis.CONTRACT)
ask(purpose="employee_directory_lookup",  destination=Destination.INTERNAL_SYSTEM, legal_basis=LegalBasis.CONTRACT)
ask(purpose="monthly_payroll_processing", destination=Destination.INTERNAL_SYSTEM, legal_basis=LegalBasis.CONTRACT, retention=Retention.PERSISTENT)
ask(purpose="monthly_payroll_processing", destination=Destination.INTERNAL_SYSTEM)                 # no legal basis
ask(purpose="monthly_payroll_processing", destination=Destination.EXTERNAL_MODEL, legal_basis=LegalBasis.CONTRACT)
```

Things worth trying to break: a purpose the pack does not know (denied by
default; a policy opts out with `require_known_purpose: false`), a field the
pack does not know, nested records (decided as one field), lists of records, a
broken policy YAML, an unknown destination or retention value. The engine
should refuse, deny or raise a clean validation error; it should never release
a field by accident. Check `r.audit` too: it must never contain a protected
value, only field names, reasons, the matching rule and the guards. To send
events somewhere other than the log, try `audit.set_sink` and make the sink
raise: the response still arrives and the event falls back to the log.

## 4. The proxy over stdio, with a real MCP host

Point Claude Code, Claude Desktop or any MCP client at a deployment. The
interpreter must be the one with moriti installed, so use the venv's path:

```json
{
  "mcpServers": {
    "moriti-hr-directory": {
      "command": "/absolute/path/to/.venv/bin/moriti-proxy",
      "args": ["/absolute/path/to/moriti/deployments/hr_assistant.yaml"]
    }
  }
}
```

Ask the agent for Sarah's salary and email. It should get the email and be
told nothing about salary, because salary never entered its context. Switch
the deployment to `payroll_agent.yaml` and ask again. The proxy's stderr shows
one audit line per call with the decisions and reasons, and no values.

## 5. The proxy over streamable HTTP

```bash
python -m moriti.mcp.demo_hr_server --http 127.0.0.1:8766                 # terminal 1: an HTTP MCP server
moriti-proxy deployments/hr_assistant_http.yaml --http 127.0.0.1:8765     # terminal 2: the proxy, HTTP both sides
```

Then any MCP client that speaks streamable HTTP connects to
`http://127.0.0.1:8765/mcp`, or:

```python
import asyncio, json
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

async def main():
    async with streamable_http_client("http://127.0.0.1:8765/mcp") as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        print([t.name for t in (await s.list_tools()).tools])
        print(json.loads((await s.call_tool("get_employee", {"name": "sarah"})).content[0].text))

asyncio.run(main())
```

## 6. The adapters, offline

The three demos in section 1 drive the ADK, Strands and ContextForge adapters
with the events their frameworks fire. The AgentCore interceptor is plain JSON
in and out; `tests/test_agentcore_interceptor.py` has the documented event
shapes, and this is the whole function:

```python
from moriti.adapters.agentcore import make_handler
from moriti.adapters.common import DeploymentConfig
fn = make_handler(DeploymentConfig.from_yaml("deployments/hr_assistant.yaml"))
print(fn(event))     # event: any of the shapes in the tests, or one captured from a gateway
```

## 6b. The mediation service (any gateway that can call HTTP)

```bash
pip install -e ".[serve]"
moriti-serve deployments/hr_assistant.yaml deployments/payroll_agent.yaml --http 127.0.0.1:8770
curl -s localhost:8770/deployments
curl -s localhost:8770/mediate/hr_assistant -H 'content-type: application/json' \
  -d '{"tool":"get_employee","arguments":{"name":"sarah"},"result":{"name":"Sarah Ndlovu","email":"s@example.co.za","salary":1450000}}'
curl -s localhost:8770/mediate/payroll_agent -H 'content-type: application/json' -d '<the same body>'
```

The first call withholds salary, the second releases it. Send it free text as
`result` and it comes back withheld. Point an Azure API Management outbound
policy at it (README, the APIM section) to run it in a real gateway.

## 6c. Microsoft Agent Framework, offline

`python -m examples.demo_agentframework` drives the middleware with the
framework's own context and tool types, for both deployments.

## 7. Live in IBM ContextForge (Python 3.12, three processes)

Follow the "Run inside IBM ContextForge" section of the README: start the
plugin server for a deployment, register it in the gateway's plugin config in
`transform` mode, call a tool through the gateway. Withheld fields should be
absent from what the agent receives; the plugin server log shows the
mediation line.

## 8. Live in Amazon Bedrock AgentCore (needs an AWS account)

Build a Lambda deployment package containing moriti and a deployment file:

```bash
mkdir -p build && pip install . -t build/ && cp deployments/hr_assistant.yaml build/
cd build && zip -r ../interceptor.zip .
```

Create the function with handler `moriti.adapters.agentcore.handler`, set
`MORITI_DEPLOYMENT=hr_assistant.yaml`, and attach it to your gateway as a
RESPONSE interceptor (AgentCore developer guide, "Using interceptors with
Gateway"). Call a tool through the gateway that returns a record with a
salary-like field, and check the agent's response and the function's logs.
This path is built to the documented contract and has not yet been run on a
live gateway; anything surprising is worth an issue.

## What to look for everywhere

- Withheld fields are absent, not masked, unless the policy says mask or tokenise.
- Every refusal is a JSON object with `"moriti": "refused"` and a reason.
- No log line or audit event ever contains a protected value.
- Changing the purpose in the deployment file changes the answer; nothing an
  agent sends does.

# Security policy

moriti is privacy infrastructure. A flaw that lets a field reach an agent it
should not, or that leaks a protected value into a log or an audit event, is a
security vulnerability and is treated as one.

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | yes       |

## Reporting a vulnerability

Please do not open a public issue for a security problem.

Use **Report a vulnerability** under this repository's *Security* tab (GitHub's
private vulnerability reporting). If that is unavailable to you, email
hello@moriti.dev with "security" in the subject; you will get a private reply.

Include what you can of:

- the moriti version and Python version;
- a minimal reproduction: the policy pack, the request context and the record,
  using **fabricated data only**;
- the decision you got and the decision you expected;
- the impact as you see it.

## What to expect

- Acknowledgement within 3 working days.
- An assessment and a plan within 10 working days.
- A fix released as a patch version, with a GitHub security advisory that
  credits you unless you prefer otherwise.

This is a small project maintained by one person. The timelines are honest;
they are not a promise of a security team.

## Scope notes

- The demo HR server, the example deployments and the policy packs ship
  fabricated data and exist for demonstration. Reports against them are welcome
  when they show a real engine or proxy flaw.
- "The runtime can be configured to release data" is not a vulnerability.
  "The runtime released data the configuration said to withhold" is.
- There is no bug bounty.

## Safe harbour

Good-faith security research on your own deployment of moriti will not lead
to legal action from the project.

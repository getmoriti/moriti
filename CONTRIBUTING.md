# Contributing to moriti

Thank you for looking. This is a small project with a clear spine, and the
easiest way to get a change merged is to keep to that spine. Taking part means
following the [Code of Conduct](CODE_OF_CONDUCT.md). To report a security
problem, see [SECURITY.md](SECURITY.md) and do not open a public issue.

## Before you start

- For anything beyond a typo or an obvious bug, open an issue or a Discussion
  first and say what you want to change and why. It saves both of us a rewrite.
- Policy packs for new jurisdictions are very welcome. Open a *policy pack*
  issue with the law, the purposes and the lawful bases you have in mind.

## Set up

```bash
git clone https://github.com/getmoriti/moriti.git && cd moriti
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"        # add ,contextforge on Python 3.12 for the gateway plugin
python -m pytest
python -m ruff check .
```

Tests must pass on Python 3.11 and 3.12; CI runs both against a freshly built
wheel, not the checkout, so a change that only works in editable mode will fail.

## The rules a change must keep

These are the properties the project exists to provide. A pull request that
weakens one of them will not be merged, however elegant.

1. **Default deny.** Nothing is released unless a rule grants it *and* every
   guard passes. A purpose the policy does not define is denied too.
2. **Rules propose, guards dispose.** A guard may only ever restrict an
   outcome. If your change lets a guard loosen one, it is the wrong change.
3. **Fail closed.** Enforcement errors redact; mediation errors refuse; output
   the engine cannot mediate is withheld, not passed through.
4. **No protected value ever reaches a log or an audit event.** Reasons name
   fields, never values.
5. **No telemetry, no phone-home, no network calls from the runtime.**
6. **No real personal data anywhere.** Tests, fixtures, examples and packs use
   fabricated people. If a fixture looks like it could be a real person, change it.
7. **Purpose is bound at deployment, never taken from the agent.**

## Style

- `ruff check .` clean.
- Type hints on public functions. Docstrings say *why*, the code says what.
- One behaviour per test, and the test name states the behaviour.

## Sign your commits (DCO)

This project uses the [Developer Certificate of Origin](https://developercertificate.org/)
rather than a contributor licence agreement. Add a sign-off to each commit:

```bash
git commit -s
```

That adds a `Signed-off-by: Your Name <you@example.com>` line, which certifies
that you wrote the change or otherwise have the right to submit it under the
Apache-2.0 licence. Contributions are accepted under that licence and no other.

Your sign-off address is public in the history. If you would rather not use a
personal one, GitHub's no-reply address (`ID+username@users.noreply.github.com`,
shown in your email settings) works, and so does any address you control.

## Pull requests

- Keep them focused. One behaviour change per pull request.
- Say what changed, why, and how you tested it. The template asks.
- Expect a review within a week. If you hear nothing, a polite nudge is fine.

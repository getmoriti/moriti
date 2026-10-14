## What and why

<!-- One behaviour change. What it does, why it is needed, what it replaces. -->

## How it was tested

## Checklist

- [ ] Tests added or updated; `pytest` passes on 3.11 and 3.12
- [ ] `ruff check .` is clean
- [ ] Default deny and fail-closed behaviour are unchanged; no guard can loosen an outcome
- [ ] No protected value can reach a log or an audit event
- [ ] No real personal data in tests, fixtures or examples
- [ ] Commits are signed off (`git commit -s`, see CONTRIBUTING.md)

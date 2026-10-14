---
title: Concepts
description: Purpose, rules, guards, decisions and the audit event.
order: 2
---

# Concepts

## The question

Identity asks who is calling. Authorisation asks whether they can reach the resource. Neither asks whether this person's data should be used this way, for this purpose. moriti asks that, on every request, before the data reaches the agent.

## Purpose is assigned, never declared

Every deployment binds one agent to one purpose, in configuration, when the agent is provisioned. An agent that could state its own purpose would state whichever one unlocks the data, so the engine would be judging a string the adversary controls. Here, purpose is organisational configuration: a privacy officer sets it, and the agent cannot vary it. An agent that needs two purposes gets two deployments.

## The request context

A decision depends on more than who is asking. Each request carries:

| Axis | Fields |
| --- | --- |
| Who | `agent`, `principal`, `principal_role` |
| What | `data_subject`, `resource`, `requested_fields` |
| Why | `purpose`, `task` |
| How | `tool` |
| Where | `destination`, `jurisdiction` |
| For how long | `retention` |
| On what basis | `legal_basis`, `consent_scopes` |

`destination` is one of `internal_system`, `internal_model`, `external_model`, `third_party_api`, `agent_memory`, `another_agent`, `human_ui`. `retention` is `ephemeral`, `session`, `long_term_memory` or `persistent`. `legal_basis` is `consent`, `contract`, `legal_obligation`, `legitimate_interest`, `vital_interest` or `public_interest`.

## Rules propose, guards dispose

A policy has two layers, and their order is the point.

**Rules** grant access the familiar way: "the payroll agent may read salary for payroll runs". The most specific matching rule wins; if none match, the policy default applies, and the default is `deny`.

**Guards** run after the rule. They can only restrict the outcome, never loosen it. There are five:

| Guard | Restricts when |
| --- | --- |
| `purpose_necessity` | the field is not in the purpose's `necessary_fields`, or the policy does not define the purpose at all |
| `consent` | consent is the legal basis and the purpose is outside the consent on file |
| `legal_basis` | the policy requires a legal basis and none is given |
| `external_transfer` | the field may not leave the organisation, or must be tokenised first |
| `retention` | the field may not be kept as long-term memory or persistent storage |

This is why an employee with legitimate CRM access can still be refused. The rule allows it. The consent on file covers marketing, the purpose is fraud investigation and the destination is a third party, so the guards take the answer down to deny and record which one did.

## Decisions

Each field gets one decision.

| Decision | The agent receives |
| --- | --- |
| `allow` | the value |
| `deny` | nothing; the key is absent |
| `redact` | a visible placeholder, `[REDACTED BY PRIVACY POLICY]` |
| `mask` | a partial value, such as `sXXXX@example.com` |
| `tokenise` | a stable token, keyed when `MORITI_TOKEN_KEY` is set (see [API reference](/docs/api)) |
| `filter` | nothing; the key is absent |
| `require_approval` | a placeholder, `[WITHHELD PENDING APPROVAL]` |
| `detokenise` | the original value, only if a reversible tokeniser is registered; otherwise redacted |

`deny` omits the key rather than nulling it, because a null still discloses that the field exists. Use `redact` when the caller must see that something was withheld.

A decision can carry obligations that travel with the released value: `do_not_store`, `do_not_send_externally`, `delete_after_task`, `ephemeral_only`, `no_long_term_memory`, `log`.

## Evidence

Every call produces an audit event: the policy and version, the purpose, and for each field the decision, the reason, the rule that proposed it, the guards that restricted it and any obligations. Events never contain field values; they can carry a data-subject reference, which is personal data. They are written to the application log by default. Register a sink with `moriti.audit.set_sink` to send them to an append-only store or a SIEM instead.

## Failure

Enforcement fails closed. If masking or tokenising a field raises, the agent gets the redaction placeholder, never the value. In the proxy, if mediation errors, the agent gets a refusal, never the unmediated result. Unstructured output is withheld rather than guessed at.

---
title: Policies
description: The policy file format, with the HR pack as a worked example.
order: 3
---

# Policies

A policy is a YAML file. Two packs ship with the package as working examples: `popia_hr_v1` and `popia_customer_v1`. They are examples of how the engine expresses purpose, consent and legal basis. They are not legal advice, so have your own counsel review any policy before you rely on it.

## A policy

```yaml
name: popia_hr
default_decision: deny          # nothing is released unless granted and guarded
require_legal_basis: true
require_known_purpose: true     # an undefined purpose is denied (the default)

purposes:
  employee_directory_lookup:
    necessary_fields: [name, email, department, job_title]   # data minimisation

fields:
  salary:
    sensitivity: high
    never_external: true        # whatever a rule says, this never leaves
    no_persistence: true        # and never becomes agent memory

rules:
  - id: directory-contact-fields
    match: { purpose: employee_directory_lookup }
    field: [name, email, department, job_title]
    decision: allow
    reason: contact details are necessary for a directory lookup
```

## Top level

| Key | Meaning |
| --- | --- |
| `name`, `version`, `description` | Identify the policy. The audit event records `name_vversion`. |
| `default_decision` | Applies when no rule matches. Defaults to `deny`. |
| `require_legal_basis` | If true, a request with no legal basis is denied. Defaults to true. |
| `require_known_purpose` | If true, a request whose purpose is not defined under `purposes` is denied. Defaults to true. Set it to false only for a policy that deliberately leaves purposes open. |
| `purposes` | What each purpose needs. |
| `fields` | Per-field properties. |
| `rules` | The ordered rules that propose a decision. |

## Purposes

```yaml
purposes:
  monthly_payroll_processing:
    description: Running the monthly payroll.
    necessary_fields: [name, employee_id, bank_account, salary, tax_number]
    compatible_with: []
```

`necessary_fields` drives the purpose-necessity guard: a requested field outside the list is denied. A purpose that is not defined under `purposes` is denied while `require_known_purpose` is true, which it is by default. A defined purpose that lists no fields is not constrained by this guard. `compatible_with` names purposes this one is a compatible secondary use of; the consent guard accepts consent given for a compatible purpose.

## Fields

| Key | Effect |
| --- | --- |
| `sensitivity` | A label for your own policy; the engine records it but does not branch on it. |
| `never_external` | Denied when the destination is `external_model` or `third_party_api`. |
| `tokenise_when_external` | Released to external destinations only as a token. |
| `no_persistence` | Denied when retention is `long_term_memory` or `persistent`, and otherwise released with `no_long_term_memory` and `delete_after_task` obligations. |

## Rules

```yaml
rules:
  - id: payroll-agent-remuneration
    match:
      agent: payroll_agent
      principal_role: hr_payroll_admin
      purpose: monthly_payroll_processing
      destination: internal_system
    field: [salary, bank_account, tax_number, name, employee_id]
    decision: allow
    reason: payroll administration requires remuneration data
```

- **`match`** keys can be `agent`, `principal`, `principal_role`, `purpose`, `task`, `tool`, `resource`, `destination`, `jurisdiction` and `retention`. A value can be a single value, a list, or `*`. An unknown key never matches.
- **`field`** is a field name, a list of names, or `*`.
- **`decision`** is any decision from [Concepts](/docs/concepts), or one of these shorthands that adds obligations: `allow_ephemerally`, `log_and_allow`, `log_and_block`, `do_not_store`, `do_not_send_externally`, `delete_after_task`.
- **Specificity.** Rules that constrain more of the context win; ties go to the rule declared first.

## Your own packs

A deployment's `policy:` can be:

1. a file path, such as `./policies/my_bank_v1.yaml`, resolved next to the deployment file first;
2. a bare name found in the directories listed in `MORITI_POLICY_PATH`, separated like `PATH`;
3. the name of a bundled pack.

Your packs win over bundled ones. Copying `popia_hr_v1.yaml` into your own directory and editing it is the whole workflow. Nothing touches the installed package.

## The deployment file

The same file configures the proxy, the ContextForge plugin, the ADK plugin and the HTTP service.

| Key | Meaning |
| --- | --- |
| `agent` | The identity this deployment serves. |
| `purpose` | The purpose bound here. |
| `policy` | A pack, as above. |
| `principal`, `principal_role` | The human the agent acts for. |
| `destination` | Defaults to `internal_model`. |
| `retention` | Defaults to `ephemeral`. |
| `jurisdiction` | An ISO country code, such as `ZA`. |
| `legal_basis`, `consent_scopes` | The basis for processing, and the purposes the data subject consented to. |
| `allowed_tools` | Tools the agent may see and call. Empty means all. |
| `downstream` | Proxy only: the real server, by `command` and `args` or by `url`. |

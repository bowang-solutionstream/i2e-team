# Policy

Policy schema `i2e-team-policy-v2` for the staged v8 profile. See the [runtime guide](runtime.md) for the policy command and the [records reference](records-v2.md) for fields.

## Roles and classification

The root session is the project coordinator. It keeps the objective, authority, current state, and continuation links. Independent review uses an eligible separate session and excludes relevant contributors.

Record the queue, risk, finding impact, and route as distinct fields.

- `queue_priority` accepts `P0`, `P1`, `P2`, `P3`, `urgent`, `normal`, or `deferred`. It orders authorized work.
- `technical_risk` accepts Low, Medium, High, or Critical. Assess blast radius, reversibility, uncertainty, and likely failure cost.
- A finding's `severity` accepts High, Medium, or Low. It describes the observed defect's impact.
- `execution_lane` accepts Direct, Standard, or Critical.

Significant architecture includes unresolved trust, concurrency, recovery, or cross-system design decisions that need Astra judgment. Unknown material risk requires read-only investigation before lane selection.

The coordinator performs the initial read-only screen. When source investigation is needed, a Sol lead or bounded Sol probe performs it. If that investigation selects Critical, use that Sol probe as round 1 and transfer local Spec Kit planning to Astra for round 2. Preserve the investigation and contributor identities. This makes intake possible before the final route is known.

## Lane table

| Lane | Entry | Plan | Worker | Independent assurance |
|---|---|---|---|---|
| Direct | One bounded Low-risk ticket with clear authority, observable acceptance, reproducible checks, adequate coverage, and no specialist or final trigger | Worker records the inline contract before writes | Sol | One fresh Sol verifier executes relevant checks and inspects the diff, assertions, and callers |
| Standard | Classified work below Critical entry, including batches | Sol planning-only lead and fresh independent Astra approval of the exact contract | Separate Sol worker | One fresh Sol verifier for eligible Low-risk candidates. Otherwise use distinct Sol code, security, and test audits |
| Critical | High or Critical technical risk or significant architecture | One Astra Spec Kit planning session after the Sol probe. Issues stay local. | Sol implements and repairs | One fresh Sol verifies full lint, E2E and accepted criteria |

New Critical runs use the [four-round controller](critical-four-rounds.md). The remaining eligibility and specialist rules in this document apply to Direct and Standard.

Reduced assurance requires the Direct eligibility conditions except the single-ticket and separate-lead conditions. Assess combined batch risk and interaction coverage. Unknown reduced-route eligibility selects baseline audits, but those audits cannot waive a missing required check.

The planning-only lead stays separate from implementation in Standard and Critical. Direct's worker plans inline and builds. A required check with a failure or unexplained `NOT_RUN` prevents reduced assurance.

## Changes during work

Reassess risk and eligibility when evidence changes. A new trigger, material uncertainty, added ticket, changed authority, or unplanned semantic dependency ends Direct eligibility. A correction within the recorded boundary does not automatically create a new ticket. One failed repair of the same finding also moves a Direct task to Standard or Critical.

Before more dependent writes, preserve the prior history, obtain the receiving lane's plan and reviews, and renew affected proof. Do not relabel earlier work as if the new route authorized it.

Sol owns the affected repair of a High finding on a new run. Bind the Sol actor to the named remediation in the exact plan and its affected start. The coordinator stays in place. Reassess technical risk and transfer the lead to Astra only if Critical-lane entry now applies. A Standard lead may retain the rest of a batch when its risk stays below that threshold. Replanning follows the contract-change rules.

A handoff records objective, acceptance, current candidate, plan revision, allowed writes, dependencies, open findings, repair counts, cases, proof limits, and exact next action. Keep the former actor as a historical contributor. Do not pretend the existing session changed its model.

## Requested settings and evidence

Start a new coordinator on Sol 6.2 Max / Fast. The [Sol preset](../agents/i2e_team_sol.toml), `i2e_team_sol`, requests `gpt-6.2-sol` at `max` with Fast service (`priority`). The [Astra preset](../agents/i2e_team_astra.toml), `i2e_team_astra`, requests `gpt-6.2-astra` at `max` with Standard service (`default`). Use Sol for bounded routine work in Direct or Standard and list the exact paths the worker may edit.

Native Codex children can inherit their root session's tier even when their role file selects a different tier. Use a named child under a matching root, or on a host with verified per-child tier selection. Otherwise start a separate top-level session at the required model, effort and tier. From the authorized worktree, pass a read-only assignment packet on stdin to the appropriate command.

```sh
codex exec --model gpt-6.2-sol -c 'model_reasoning_effort="max"' -c 'features.fast_mode=true' -c 'service_tier="priority"' --sandbox read-only --json -
codex exec --model gpt-6.2-astra -c 'model_reasoning_effort="max"' -c 'service_tier="default"' --sandbox read-only --json -
```

For an authorized worker, use the qualified write mode from the plan. For an independent reviewer, supply only the neutral review packet. Preserve launch settings, session identity and result. Codex sends Standard by omitting the service-tier override. Apply the selected `tier_policy` to provider evidence.

Record requested and host-recorded model, effort, session identity, and context provenance separately. Collect host evidence from the actual dispatch and session. Self-reports and prompt labels are insufficient. A bounded read-only setup interaction may collect missing evidence before any production assignment.

Hold production dispatch on an unavailable model, a reported model/effort mismatch, absent required identity evidence, or an unvalidated write mode. Hold an independent review assignment if its required identity or contribution history cannot be established.

The policy selects `tier_policy`.

- `require_match` is the default. Unknown or mismatched effective tier holds the affected operational dispatch.
- `record_unknown` requires an actual owner `TIER_POLICY` decision recorded before the plan. An effective tier may remain UNVERIFIED. A reported mismatch requires the exact owner-authorized alternate for that session.

A tier exception does not relax model, effort, independence, authority, or write-safety requirements. Read-only design review is distinct from qualifying an operational v8 role. Record its actual provenance without claiming v8 runtime compliance.

Qualify actual model and effort requests and effective tier on the selected host interface. A priority setting or role prompt supplies no effective-tier evidence.

## Specialists and final review

Assess all seven final triggers: consequential authorization or tenant changes; destructive migrations; critical financial behavior; uncertain cross-system interactions; material redesign; conflicting reviews; user or project requirements.

Any true trigger requires a fresh Astra final review after all other obligations. An unknown trigger blocks the dependent decision.

Security review applies to authentication, tenants, secrets, sensitive data, and trust boundaries. Test expertise applies to weak assertions, substantial behavior changes, concurrency, retries, or unclear reproduction. Significant architecture and repeated-repair diagnosis use Astra.

An eligible security or test audit may cover its matching specialist obligation with observed evidence. Keep the three baseline auditors distinct. A selected architecture obligation requires a separate current Astra `audit` of kind `architecture`, in addition to the Sol baseline audits and before the distinct final Astra.

Reviewers exclude all relevant planners, coordinators, implementers, and other contributors. Final Astra also excludes prior relevant plan, doubt, audit, verification, and escalation participants.

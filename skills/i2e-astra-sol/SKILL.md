---
name: i2e-astra-sol
description: Run the four-round Critical Astra/Sol I2E workflow with Sol probing, Astra Spec Kit planning and local issues, Sol implementation and fresh Sol verification. Use the staged v8 controller for Direct and Standard evaluation.
metadata:
  profile: i2e-team/v2
  revision: v8
  status: STAGED_NOT_INSTALLED
  critical_workflow: critical-four-v1
---

# I2E Astra/Sol coordinator

The root coordinator owns progress and evidence. Independent approval requires an eligible separate session.

For new Critical work, use the [four-round Critical workflow](references/critical-four-rounds.md). It is shared with the installed Astra/Sol skill. The Direct and Standard v8 package retains its staged status. Existing runs use their recorded profiles. See [adoption](references/adoption.md).

First, run the [library fetch](scripts/fetch_library.py) before project inspection, planning, dispatch or edits on every new or resumed invocation. Continue only after the latest properties and rules from `main` validate. Record the fetched revision and selected IDs. At successful handoff, reflect on verified findings and publish any new public-safe properties or rules. An empty or duplicate reflection creates no commit. Follow the [intake and handoff procedure](references/critical-four-rounds.md#shared-library-at-intake-and-handoff).

## Select the lane

Read [policy](references/policy.md). Establish the objective, authority, repository, current worktree, acceptance, technical risk, and relevant triggers. Use read-only investigation when classification is unclear. Queue urgency orders work. Model selection uses technical risk, architecture, and lane eligibility.

| Lane | Plan and build | Independent assurance |
|---|---|---|
| Direct | One clearly bounded Low-risk ticket. The worker records an inline contract and builds. | One fresh Sol verifier |
| Standard | Sol planning-only lead; fresh Astra plan approval; separate workers | Eligible Low risk: one verifier. Otherwise: three distinct Sol audits |
| Critical | Sol probes. Astra specifies the deliverables with Spec Kit and creates session-local issues. Sol implements. | One fresh Sol runs full lint, E2E and criterion-by-criterion acceptance |

Use the Critical guide for all four assignments, including significant architecture. For Direct and Standard, apply their eligibility and specialist rules. Unknown risk limits the next action to read-only investigation. Use Sol 6.2 Max / Fast and Astra 6.2 Max / Standard. Native children can inherit their root's tier. Use the named role under a matching root or [start a separate session at the required speed](references/policy.md#requested-settings-and-evidence). Verify the dispatch against host evidence.

## Run Direct and Standard work

For behavioral work, select the applicable versioned properties and learned rules during planning. Read [project catalogs and rule promotion](references/verification.md#project-catalogs-and-rule-promotion) when adding a feature or recording a miss. The [label pilot](references/verification.md#portable-label-pilot) is a runnable example.

1. **Prepare.** Read [execution](references/execution.md) and the [runtime guide](references/runtime.md). Select the exact qualified controller. Record instructions, dirty state, dependencies, known cases, and permitted actions.
2. **Plan.** Bind acceptance, exclusions, risk, tests, authority, and an explicit write boundary. For E2E or property checks, [select the tools](references/verification.md#select-verification-tools) for the user journey and implementation language. Pin the project verifier and selection in the plan. For Standard, obtain exact-plan approval with [the plan-review prompt](prompts/plan-review.md).
3. **Dispatch.** Verify actor identity, model/effort, selected tier policy, contribution history, and the supported write mode. Give the worker [its prompt](prompts/implementation.md) and only relevant context.
4. **Build.** Inspect the actual preflight before each dependent action. Observe unregistered paths in zero-write VERIFY. Preserve TEST_ONLY assertion RED and PRODUCTION GREEN on unchanged tests for behavioral work.
5. **Integrate.** Accept a named commit only from the current authorized attempt. Record the actual combined candidate, base, harness, dependencies, and checks.
6. **Verify.** Use [the verification prompt](prompts/verification.md). Reviewers execute key checks and inspect source. Complete required specialists, finding rechecks, final case regressions, and triggered final review.
7. **Deliver.** Read [delivery](references/delivery.md). Check current evidence and action authority. Require a qualified target and enforce source and target conditions through the selected adapter. Reconcile the actual result.
8. **Finish.** Report observed local acceptance, PR, CI, merge, deployment, and customer acceptance states. Follow with the [engineering brief](references/teaching.md). Keep uncertain workspaces and report pending cleanup.

## Direct and Standard controls

Expected file lists help planning. Before adding a file, check the approved boundary and semantic impact, then record the controller's observed path identity. A changed contract needs renewed approval before dependent writes.

Batch decomposed work into at most five bounded tickets. Preserve per-ticket proof and interaction checks. Record removed tickets as continuation work under the still-open parent request.

Read [verification](references/verification.md) for failure classification. Save first-failure evidence before correction. Canonical defects retain their cases, regressions, and repair counts. Two failed repairs require Astra diagnosis before a third.

Report material findings with evidence. Keep Low observations compact. Retain the distinct independent rechecker for fixed findings. Three unresolved cycles of one decision stop dependent work.

Before cleanup, preserve recoverable source and evidence, account for local files and dependencies, and establish whole-writer quiescence or effective revocation.

A relevant source, base, harness, or profile change invalidates affected proof. Unknown evidence stays unknown. No per-run budget gate is added.

For capability tests, exploratory trials, and profile activation, use [adoption](references/adoption.md).

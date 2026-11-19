# Execution

New Critical work uses the [four-round Critical workflow](critical-four-rounds.md). The v8 procedures below cover Direct, Standard and replay of runs already recorded under the earlier profile.

Use these rules for the staged `i2e-team/v2` controller. Existing runs keep their recorded profile. See the [legacy runtime guide](runtime-v1.md) for v1 records.

## Intake and controller base

Record the repository and client boundary, original request, instructions, dirty state, allowed actions, acceptance, dependencies, and known cases. Do not change a repository's visibility or branch rules as an intake side effect.

V2 intake records the actual first bytes and Git modes of the worktree paths, including dirty intake. First observations of additional paths use the pinned Git base as their baseline.

Select an exact controller version. Retain the installed helper, corrected baseline, and staged source identities when they are relevant. Bind checks to the artifact actually executed.

Verify readiness, command receipts, acceptance coverage, current plan and source binding, and lawful narrow repairs against the selected controller.

Fix the controller governing a runtime implementation independently of the changing candidate. Record its exact identity and actual preflight outcomes.

## Plan contract

Before writes, record an immutable contract with:

- Original objective, ticket IDs, acceptance and required checks.
- Exclusions, allowed actions, release and rollback intent.
- Lane, risk, triggers, contributor identities, and required review.
- Concrete authorized write surfaces and protected exclusions.
- Dependencies, test areas, relevant callers, and interaction obligations.
- Batch membership and any explicitly detachable tickets.
- Current source/base and the governing instruction/profile identity.

Standard requires fresh Astra approval of this exact revision. Direct requires the inline contract and authority record, but omits that independent plan approval.

The contract grants concrete write authority. `expected_files` is an optional planning aid for scope and parallel ownership.

Before editing an unregistered path, submit `observe_manifest` in a source-preserving `VERIFY` preflight with empty write grants. Record the literal path, ticket, role, pinned-base bytes or absence, callers, dependencies, checks, and unchanged technical risk. Read back the expanded candidate and the controller-observed physical identities. The first observation binds the path, ticket, role, bytes, presence, and Git mode. A later TEST_ONLY or PRODUCTION request uses `write_manifest` and binds the current before-candidate.

Immutable instructions, proof harnesses, dependencies, and exclusions take precedence. Initial mapped role and ticket ownership and established observations also take precedence over a reviewed surface. New observations must match the pinned Git base in bytes and mode or in absence. Resolve exact on-disk spelling and reject symlink, hardlink, and case or Unicode alias collisions.

Refresh affected proof on the expanded candidate. Unchanged contract terms can use the existing approval. A change to a dependency, protected surface, risk, acceptance, authority, or other material term requires a revised contract and the receiving lane's approval before dependent writes.

## Ordered phases

VERIFY grants zero source writes. It preserves source and instruction bytes and modes while observing paths and collecting checks. A mapped native CHECK may refresh current acceptance or case coverage under its exact approved `verification_map`.

TEST_ONLY changes only the approved test area and preserves production bytes and modes from the earliest open TEST_ONLY baseline. Preserve a meaningful behavioral assertion failure and its full harness identity. After registering a path, obtain fresh exact RED on the expanded before-candidate for the affected cycle.

PRODUCTION changes approved production files and preserves test bytes and modes. A regular production file may change its execute bit within the approved grant. The matching RED binds the full phase-before source, plan, base, harness, dependencies, exact test bytes and mode, runner, and command. The corresponding GREEN keeps the test and execution identity identical. Test changes start a new authorized test cycle and invalidate affected proof.

Direct uses these semantics too. Its smaller plan route is not a behavioral-test waiver. Nonbehavior changes use proportionate checks without fabricating RED.

Inspect the actual preflight result before each dependent action. Authority applies from its recorded grant. VERIFY may refresh required checks between work phases while an unfinished cycle stays open. Bounded remediation may defer its exact named failed obligations. Retain unrelated prerequisites and exact inherited case links.

The PRODUCTION grant includes only production paths. Read back `write_scope`, the actual manifest, test identity, and the recorded phase boundary. See the [records reference](records-v2.md) for request fields.

## Batches

Decomposed requests use batches with at most five bounded tickets. A single ticket is a batch of one. Do not wait to fill five. Count logical accepted tickets, not files, commits, or tool calls.

Use compatible tickets with coherent dependencies and rollback. Runtime code checks unique IDs, membership, count, and mappings. The existing independent reviewer checks the actual diff against the original request. This adds no separate scope-review role.

Preserve per-ticket checks and applicable RED/GREEN. The current required checks combine retained ticket checks, global required checks, and every approved `batch.interaction_checks` entry, with duplicates removed. Each interaction applies to full intake and each selected subset. The selected proof binds the exact current plan, full candidate, and membership in its issuance prefix. After a membership change, obtain fresh interaction proof. Stale or retired selected interaction proof holds readiness. One failed ticket holds that batch until repair or a valid split.

A plan may explicitly delegate removal of named independent tickets. Its approved contract retains the full request and defines the permitted nonempty candidate subsets. Record the current subset in a versioned membership manifest; do not rewrite the approved contract. The lead may use that delegation without another full approval only if:

1. Remaining acceptance, authority, lane, risk, and write boundaries are unchanged.
2. No remaining ticket depends on the removed work, its checks, or its rollback behavior.
3. The removed tickets' initial mapped paths and observed owned paths match their immutable first bytes, presence, and mode.
4. Findings, cases, repair counts, and the removed ticket remain linked to explicit continuation work.
5. The delivery scope permits the subset. An accepted delegated subset can deliver while its original parent stays open for the recorded continuations.

Record the decision and new candidate membership. An unplanned removal or failed condition requires a revised plan and its required approval. The rule does not permit silent cancellation or a false parent completion.

A dependent local batch starts from an exact accepted predecessor commit. Retain its acceptance receipt and unresolved inherited obligations. Review the new delta against that base. A changed or superseded predecessor invalidates affected proof.

For later GitHub delivery, merge predecessors first. Reconcile the dependent branch against the real target and refresh affected proof. Its delivery diff cannot hide unmerged predecessor tickets. Stacked-PR automation is outside the first implementation.

## State and orchestration

Use the ledger's append-only events, immutable evidence references, expected-sequence updates, and current attempt identity per ticket. Derive readiness from required obligations.

`check` reports `HOLD`, `REWORK`, `VERIFYING`, `ACCEPTED_LOCAL`, or `DELIVERED` for a v2 plan. A repair, withdrawal, or relevant source change can revoke readiness. Read the specific operation receipt for worker, evidence, and delivery outcomes.

The staged worker adapter supports contained synthetic commands. Before selecting operational workers or parallel write scopes, qualify actual host transport and compatible ownership. On restart, reconcile existing attempts, artifacts, and external results before redispatch. A revoked attempt cannot submit newly accepted output.

A terminal model turn is not task completion. Technical readiness precedes the completion report. The brief and final consistency result must agree with the actual candidate and remaining obligations.

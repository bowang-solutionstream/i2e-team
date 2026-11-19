---
name: i2e-opus-sonnet
description: Run an Issue-to-Edit workstream with Opus 5.5 Max decisions and review, and Sonnet 5.5 Max implementation. Use for /i2e-opus-sonnet, requests for the i2e-opus-sonnet workflow, issues, PRs, and repository changes where Opus leads and Sonnet implements, or reflecting on the shared i2e property and rule library.
---

# I2E Opus Sonnet

First, run the [library fetch](scripts/fetch_library.py) before project inspection, planning, dispatch or edits on every new or resumed invocation. Continue only after the latest properties and rules from `main` validate. Record the fetched revision and selected IDs. At successful handoff, reflect on verified findings and publish any new public-safe properties or rules. An empty or duplicate reflection creates no commit. Follow the [intake and handoff procedure](references/library.md).

Deliver the requested outcome with one continuing Issue-to-Edit contract. This
package contains the workflow, issue, engineering, verification, and handoff
guidance; no other workflow skill or issue-to-edit repository is required.
Repository-specific instructions and acceptance requirements still apply.

The engineering workflow foundations credit
[Addy Osmani's agent-skills](https://github.com/addyosmani/agent-skills), adapted
here for standalone I2E orchestration. See [credits and license notices](NOTICE.md)
for the retained upstream attribution; no upstream installation is required.

## Start with the requested outcome

Classify the request as learning, issue scoping, implementation, review, or shipping.
An implementation request authorizes the relevant local edits and verification;
do not turn it into a planning-only response. An audit or explanation stays read-only.
Use routine repository conventions to resolve ordinary details. Ask only for a
missing decision that materially changes the outcome or an action's authority.

Inspect the worktree and applicable repository guidance, then the relevant source,
issue, or PR. Note the repository's verification assets, such as a `verify` skill, a
feature map, or `REVIEW.md`, and look up the matching properties and rules in the
shared [library](references/library.md). Use the revision fetched before this invocation and record the relevant IDs. Read enough to establish the behavior and
proof; do not tour every document. Preserve unrelated changes. For substantial work,
maintain one compact record using [the run record](templates/run-record.md); reuse
it across agents. Tiny edits need only a clear outcome and proportionate evidence.

Carry forward applicable user authorization from this session and existing
workflow records. Invocation chooses the workflow; it does not grant unrelated
external actions. Do not seek the same permission again. Keep a material missing
approval confined to the affected action while completing independent authorized
work. See [issue and authority guidance](references/issue-contract.md) when
scoping, splitting, or working from an issue.

Teammate takeovers are supported. An issue's creator, assignee, or previous I2E
lane is coordination context, not an exclusive work lock or an extra approval gate.

## Route work deliberately

For substantial implementation, use **claude-opus-5-5 / max** for the decision lead
and review, and **claude-sonnet-5-5 / max** for bounded implementation, through the
bundled `i2e-opus-lead` and `i2e-sonnet-implementer` subagents. Verify actual
runtime support and use [model routing](references/model-routing.md) before
delegating. If the coordinator already is Opus 5.5 at max effort, plan and review
locally; do not introduce another planner. Never silently substitute a model or
report routing that did not happen.

Keep tiny edits, explanation, scoping, and ordinary review in the current agent
when delegation offers no material benefit; disclose actual execution. Opus owns
unresolved architecture and consequential invariants, and can implement a critical
portion directly. Each Sonnet implementer receives a cohesive write scope, the
contract, relevant evidence, and verification commands. When the work splits into
several cohesive slices, multiple Sonnet implementers may each own one; run them in
parallel only for independent write sets. The coordinator integrates and owns the
final result.

## Implement, prove, and finish

Read [engineering guidance](references/engineering.md) when implementing and apply
the entries relevant to the touched surface. Use existing patterns and small
reviewable changes. A failed local test is evidence to diagnose and repair within
scope, not an automatic request for renewed permission. Follow
[verification and review](references/verification.md) to choose proof and review
depth. Prove user-facing and integration behavior end to end on the running system,
and add property or differential tests where they fit
([verification loops](references/verification-loops.md)). Retain all required
repository gates; repeated checks need a changed input, new failure, or unresolved
concern.

After two unsuccessful repair rounds, Opus reassesses the contract and takes over or
narrows the worker assignment. Escalation changes who solves the problem; it does
not declare the task finished or automatically end authorized work. If the same
required check still fails after a third round, stop that item and bring the
evidence to the user.

Complete only when the requested acceptance criteria and required proof are
satisfied and the appropriate reviewer approves the actual final state. Missing
required proof means incomplete, with the precise gap recorded. A model verdict is
judgment, not permission to release. Perform authorized issue/PR/ship actions with
readback under [handoff and shipping](references/handoff.md). Report the outcome,
evidence, actual routing, material repairs, and remaining limits without empty
checklist fields or invented cost savings. After successful delivery, run [post-delivery reflection](references/library.md#reflect-at-successful-handoff). Publish public-safe candidates to the category branches, then record the merge to `main`, a no-change result, or a pending update. A request to reflect on
the library follows [the library guide](references/library.md) and changes no
project repository.

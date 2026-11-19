# Verification and independent judgment

Start with the smallest evidence that proves the changed behavior, then satisfy
all applicable repository/issue requirements. Reuse a recorded result only when
its candidate, inputs, environment, and relevant dependencies remain valid. New
edits, failures, or unresolved concerns justify reruns; reassurance alone does not.
Receipts and model conclusions never substitute for inspecting source and raw output.

| Surface | Useful proof |
| --- | --- |
| Documentation/configuration | Diff review; links, format, or schema where relevant |
| Typed implementation | Affected-package typecheck/lint and behavioral tests |
| Bug or new logic | Intended-assertion RED, GREEN on the unchanged test, boundary/error cases |
| API/schema | Caller compatibility and integration/contract evidence |
| UI/user flow | End-to-end run of the real flow with a step trace and screenshot, including leaving each view and coming back, plus component checks |
| Integration/backend flow | The service running locally, driven by an API harness or real requests |
| Parser, encoder, invariant, idempotent operation | Property tests with a recorded seed; minimal failing inputs kept as regression tests |
| Persistence/migration | Data-preservation, retry/restart and restore evidence |
| Behavior-preserving rewrite | Differential test against the old system, with approved differences listed |
| Build/CI | Required checks for the exact candidate revision |
| Deployed service | Deployed revision, health/smoke, observed behavior and rollback |

Use the project's commands. Run targeted tests while working, and run the full test
suite, build, and linter once on the final candidate, again only when code changes
after that. Browser sweeps are required when the touched behavior or repository
calls for them. Treat external calls as actions with their own authority and cost.
[Verification loops](verification-loops.md) describes end-to-end, property, and
differential proof, and how to keep the checks honest.

## Candidate

Bind the final checks and each review verdict to a candidate: the `HEAD` commit and
a SHA-256 of the scoped diff, with new files included. Outside Git, hash the scoped
files and say so. A changed candidate makes earlier verdicts stale for what changed,
and the next review round looks at that change.

## Test-first proof

Before a behavioral production change or repair, run the test that covers it on
the current before-state and confirm that the intended assertion fails. A syntax,
import, setup, or infrastructure failure is not RED. Keep the output. After the
change, rerun the same test for GREEN. Record the test ID and command both times,
and confirm with the diff that the test did not change in between; a changed test
needs a new RED. A reasoned nonbehavioral exception applies only to nonbehavioral
work. A behavioral deviation needs the user's actual authorization and is reported
as a deviation, never as test-first.

## Doubt reviews

A doubt review challenges one hard-to-reverse decision before work depends on it,
and runs only with the user's approval;
[model routing](model-routing.md#doubt-reviews-need-the-users-approval) says when to
propose one and what to tell the user. Give the reviewer a neutral question. It
cannot be an author or contributor of the decision, and self-review by the working
session never stands in for it. Resolve every finding with evidence; an unresolved
finding blocks the dependent work. A declined review is recorded, and the main
reviewer looks at that decision.

## Failed or missing proof

Diagnose failures in the requested scope and repair them under existing authority,
following [failure cases](failure-cases.md). Record pre-existing failures separately
with a baseline where practical; do not silently waive a required gate. Missing
credentials can leave an integration proof pending while local work continues. If
required proof remains unavailable, report incomplete and specify the missing
evidence. Only a real access constraint, a non-waivable gate, a consequential user
decision, or a required check that still fails after three repair rounds blocks its
dependent work. Repairs stay with the Opus working session; repeated failures do not
trigger automatic Fable escalation, but a material design change returns to Fable
planning. Never skip a flaky test, add sleeps, or rerun it until it passes. If the
same required check still fails after three repair rounds, stop that item and bring
the evidence to the user.

## Review standard

Every review assesses correctness, omitted requirements, maintainability,
architecture, relevant security boundaries, and runtime efficiency. Inspect the
resulting code and test assertions, not only a worker's summary or pass counts.
Revisit the requirements independently: the implementation and its tests may
share a mistaken assumption. Distinguish blocking defects from optional
preferences. An interim approval means requirements and proof are satisfied with
no unresolved blocking defect; it does not mean the code is perfect. A doubt review
is stricter: every finding it raises must be resolved.

## Blind-spot checks

Reviews tend to confirm what they are pointed at: the contract, the plan's risks,
and the tests that exist. Four kinds of defect pass that way. The working session
runs the checks that apply before the final proof, and the final reviewer runs them
again on its own. Record the evidence for each, or why it does not apply.

- **Leave and come back.** For a screen or other stateful flow, walk every way a
  person can leave the state and return: another tab or panel, another record or
  route, a save that makes a new version, a reload, a window resized while the
  view is hidden. Say what is kept, what is lost, what is fetched again, and
  whether layout and measurements are right on return, including the frame in
  which the old view is still closing. When a review notices that something
  unmounts, resets or refetches, it also says what the person loses. A code comment
  that something starts again is not a requirement that it should. When a change
  keeps state that used to start again, check what starting again gave for free,
  such as a retry after a failure or a fresh read.
- **Every path to each message.** For each message, empty state or error the
  change shows, list every condition that reaches it and check the words against
  the data model, research and contract. One message for causes the person must
  act on differently is a defect, even when no current data reaches some of them,
  as with a route that is not built yet. A test that asserts a message proves that
  the code shows it, not that it is right for every cause.
- **Documents against each other.** Before the final review, compare the change's
  documents with one another and with the code: spec, plan, research, data model,
  contracts, tasks and quickstart. Use the repository's cross-document check where
  it has one (`/speckit-analyze` in a Spec Kit repository), and compare the terms
  yourself where it has none. One word of a requirement that disagrees with the
  approved decision is a finding. A check that quoted text exists does not prove
  that the documents agree.
- **Break it on purpose.** Where a test helper decides pass or fail with its own
  predicate, such as a geometry or range check, a boundary comparison or a parser,
  break the production output at that boundary in a scratch copy and confirm a
  test fails: a line exactly on an edge, a value equal to a limit, an off-by-one.
  A helper that copies the code's own comparisons shares the code's blind spot. A
  stub that stands in for the platform, such as a fake observer or a layout mock,
  needs the same proof: the test fails when the fix is reverted, and when it is
  done another wrong way.

## Security audit

When the change touches a trust boundary listed in
[model routing](model-routing.md#security-audit-and-main-code-review), a fresh
`i2e-opus-security-auditor` reviews it after the final proof. Its report gives
`PASS`, `BLOCKED`, or `INCOMPLETE`, with findings that have `id`, `severity`
(Critical, High, Medium, Low, or Info), `blocking`, `status` (`OPEN` or `RESOLVED`),
`reason`, location, and evidence. Critical and High block; others block when the
contract or a real boundary demands it. A BLOCKED or INCOMPLETE report stops
readiness until it is resolved and the auditor confirms the fix.

## Main code review and completion

The fresh `i2e-fable-final-reviewer` is the main reviewer. It gets the contract, the
plan, the current diff, relevant callers, tests and raw check output, end-to-end and
blind-spot evidence, failure consultations, base-revision copies of `REVIEW.md` and
the reliability checklist, the adopted library rules that match, the doubt-review
outcomes and any declined or unasked review, and the security report if one ran. It
reviews the contract and tests before the production code; checks correctness at
boundaries, error paths, and concurrency; looks for tests that mirror the
implementation, masked negative assertions, and user-facing behavior without
end-to-end evidence; and runs the blind-spot checks again on its own.

Each finding has a severity of Critical, Required, Optional, or Nit, and a defect
that existed before this change is marked Pre-existing. APPROVE requires every
Critical and Required finding resolved; Optional, Nit, and Pre-existing findings
stay disclosed and do not block unless the contract covers them. REVISE means the
findings can be fixed within the current plan; BLOCK means approval needs a material
redesign, missing authority, or proof the run cannot produce. Keep REVISE or BLOCK
evidence. After fixes, the working session reruns the affected tests and flows, then
the full suite, build, and linter once on the fixed candidate, and the same reviewer
checks its earlier findings and the change since its last round. A material redesign
returns to Fable planning and gets a fresh reviewer.

Before reporting completion, check the record for consistency:

- every acceptance criterion maps to a required check that passed on the final
  candidate;
- user-facing and integration behavior has end-to-end evidence from the running
  system, or a recorded proof gap;
- no change weakened a check that judges it unless the contract allowed it;
- every behavioral work item has RED before it and GREEN after it on the same
  unchanged test, or a recorded exception or user-approved deviation;
- every unexpected failure was captured before its repair, and every
  ever-applicable case has a passing regression check on the final candidate;
- every blind-spot check that applies has its evidence on the final candidate, and
  every one that does not has its reason;
- every doubt review the user approved is resolved, and every declined or unasked
  one is recorded;
- the security audit, when a trigger applied, passed on the final candidate;
- the main review approves the final candidate;
- the actual subagents, models, and efforts are recorded, with any missing lane.

This check is consistency evidence. It cannot authenticate model identity, human
intent, or actual execution, and it does not authorize release. A required failed
or missing check never becomes a completed task merely because it was documented
accurately. A completed local implementation can still have an explicitly
separate, unrequested deployment phase.

# Verification and independent judgment

Start with the smallest evidence that proves the changed behavior, then satisfy
all applicable repository/issue requirements. Reuse a recorded result only when
its revision, inputs, environment, and relevant dependencies remain valid. New
edits, failures, or unresolved concerns justify reruns; reassurance alone does not.

| Surface | Useful proof |
| --- | --- |
| Documentation/configuration | Diff review; links, format, or schema where relevant |
| Typed implementation | Affected-package typecheck/lint and behavioral tests |
| Bug or new logic | Regression or outcome test; boundary/error cases |
| API/schema | Caller compatibility and integration/contract evidence |
| UI/user flow | End-to-end run of the real flow with a step trace and screenshot, plus component checks |
| Integration/backend flow | The service running locally, driven by an API harness or real requests |
| Parser, encoder, invariant, idempotent operation | Property tests with a recorded seed; minimal failing inputs kept as regression tests |
| Persistence/migration | Data-preservation, retry/restart and restore evidence |
| Behavior-preserving rewrite | Differential test against the old system, with approved differences listed |
| Build/CI | Required checks for the exact candidate revision |
| Deployed service | Deployed revision, health/smoke, observed behavior and rollback |

Use the project's commands. Full-suite checks, builds, and browser sweeps are
required when the touched behavior or repository calls for them, not merely after
every edit. Treat external calls as actions with their own authority and cost.
[Verification loops](verification-loops.md) describes end-to-end, property, and
differential proof, and how to keep the checks honest.

## Failed or missing proof

Diagnose failures in the requested scope and repair them under existing authority.
Record pre-existing failures separately with a baseline where practical; do not
silently waive a required gate. Missing credentials can leave an integration proof
pending while local work continues. If required proof remains unavailable, report
incomplete and specify the missing evidence. Only a real access constraint, a
non-waivable gate, a consequential user decision, or a required check that still
fails after three repair rounds blocks its dependent work. Never skip a flaky test,
add sleeps, or rerun it until it passes. If the same required check still fails
after three repair rounds, stop that item and bring the evidence to the user.

## Review standard

Assess correctness, omitted requirements, maintainability, architecture, relevant
security boundaries, and runtime efficiency. Inspect the resulting code and test
assertions, not only a worker's summary or pass counts. Revisit the requirements
independently: the implementation and its tests may share a mistaken assumption.
Apply base-revision copies of `REVIEW.md`, the reliability checklist, and the
adopted library rules, choosing the items whose triggers match the diff yourself,
and give each new review round the earlier round's findings. Confirm that
user-facing behavior has end-to-end evidence and that no check that judges the
change was weakened without the contract allowing it.

Scale review to risk. The Opus lead can review normal Sonnet work. Use a fresh
Opus reviewer for consequential or hard-to-reverse changes. Review should identify
concrete failures and necessary repairs; distinguish optional preferences from
blocking defects. Approval means requirements and proof are satisfied with no
unresolved material defect; it does not mean the code is perfect.

The final reviewer reviews the final patch after repairs, reusing still-valid
evidence. A required failed or missing check never becomes a completed task merely
because it was documented accurately. A completed local implementation can still
have an explicitly separate, unrequested deployment phase.

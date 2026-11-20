---
id: rule-re-prove-a-change-whose-base-moved
kind: rule
type: review
status: candidate
tags: rebase, ci, pull-request, review
applies-to: any
seen-in: a change adding saved test cases to rules and running them before release (2026-11), an AI change dialog with a line diff in a React and Base UI app (2026-11)
updated: 2026-11-20
---

# A change whose base moved is compared with what was approved and proven again

## Trigger

The base of a branch moves during a long verification (a gate, a break run, a review round), or a change that a review approved is rebased, merged or reapplied onto a newer base, especially with a conflict resolved by hand or a shared function that the base and the change both use.

## Check

- Run `git ls-remote origin refs/heads/main` (not the shared remote-tracking ref, which another session's fetch can move) before the final proof and before pushing; when main has moved, rebase first and prove the rebased candidate.
- Rebuild the approved version of every file the change touches from the old base and the approved diff, and compare each with the moved version: only conflicted files may differ, and in those, compare the lines removed and added on each base.
- List what the base changed in shared paths and their existing consumers (a cap, a cut, a filter, a field, a moved constant) and apply each to the change's new consumers, with an agreement test large enough to reach every cap. Walk the screens the rebase changed indirectly, and re-read the change's documents for claims the new base made false.

## Why it flags

Proof on an old base can be stale, a hand resolution can keep lines no review saw, and a consumer written against the old base keeps the old behaviour, so answers that should agree drift and limits the base added do not hold on the new path.

## Cases

- Main moved three times during one feature's final checks; each time the run was stopped, rebased and re-proven.
- A conflict resolved by keeping both sides' removals left a doubled blank line that neither side had, and a decision record said another screen did not call a route that the new base had just made it call.
- After a rebase, a new test-run answer still sent a whole trace that the base had started cutting to 20 rows (about three times the size on a 200-row test), and a new audit action showed a raw record id that the base's audit screen never prints.

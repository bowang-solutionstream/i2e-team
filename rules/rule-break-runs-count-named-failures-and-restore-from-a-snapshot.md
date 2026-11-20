---
id: rule-break-runs-count-named-failures-and-restore-from-a-snapshot
kind: rule
type: test
status: candidate
tags: mutation-testing, evidence, tooling, worktree
applies-to: break-it-on-purpose and mutation runs
seen-in: a change adding saved test cases to rules and running them before release (2026-11)
updated: 2026-11-20
---

# A break run counts only named failures and is checked against a snapshot when stopped

## Trigger

A mutation or break-it-on-purpose script (plant a defect, run its tests, restore) decides a defect was caught from the test run's exit status alone or keeps only a summary, or such a run is stopped part way.

## Check

Count a check as caught only when a named test fails, by an assertion or by the error that is the planted defect; mark a run whose only errors are timeouts or setup failures as not proven; keep each run's raw output beside the table. After a stopped run, compare every file in scope with a read-only snapshot of the candidate and restore any that differs, then check the candidate's identity before editing or committing.

## Why it flags

A test file that fails in its setup, or a test that times out under load, exits non-zero without exercising the defect, so the table claims proof it does not have. The script restores each file in a finally block that a killed process never reaches, so a stopped run leaves its planted defect in the tree for the next commit to ship.

## Cases

- One row ran no test at all (every test skipped after a setup hook failed) and eight more failed partly on timeouts in tests the defect could not reach, all counted as caught.
- Three stopped runs in one session each left a planted defect; each was caught by the identity check and restored from the snapshot.

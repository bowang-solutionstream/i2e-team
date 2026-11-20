---
id: rule-a-gate-record-can-be-removed
kind: rule
type: review
status: candidate
tags: workflow, release-gate, data-lifecycle
applies-to: release or approval gates over stored records
seen-in: a change adding saved test cases to rules and running them before release (2026-11)
updated: 2026-11-20
---

# A stored record that a gate requires can be removed or retired

## Trigger

A release, publish or approval gate requires every stored record of some kind to pass (every test case, every check), and the diff adds that kind with no way to remove or retire one.

## Check

There is an audited way to remove or retire a record, and anything that re-adds records (a seed top-up, a sync) respects the removal. Test that removing a failing record lets the gate pass.

## Why it flags

One wrong or out-of-date record blocks the gate for good, and with no roles anyone can add one.

## Cases

Saved test cases had no removal while every release needed all of them to pass; a delete route with an audit row fixed it, and the seed skips a demo test case once one of its name was removed.

---
id: rule-keep-routing-metadata-out-of-profile-comparisons
kind: rule
type: review
status: candidate
tags: routing, compatibility, ledger
applies-to: versioned workflow controllers
seen-in: public four-round controller routing migration
updated: 2026-11-19
---

# Check profile compatibility when adding routing metadata

## Trigger

A workflow adds a routing revision while also comparing a run's recorded profile with the current engine profile.

## Check

Start an ordinary run, read it back through the public controller, and check that its profile compares equal to the observed engine identity while the separate routing revision selects the intended workflow. Replay an older run through its recorded profile.

## Why it flags

Adding a routing discriminator to one side of an identity comparison can make newly opened runs look historical and send normal work through the wrong gate.

## Cases

[Published round-routing regression](https://github.com/bowang-solutionstream/i2e-team/blob/52d9d48b059c57f434bbd69863f1df4a9b04bfaf/tests/test_i2e_team.py#L665-L670)

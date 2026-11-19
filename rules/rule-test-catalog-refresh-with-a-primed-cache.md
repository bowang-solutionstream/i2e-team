---
id: rule-test-catalog-refresh-with-a-primed-cache
kind: rule
type: test
status: candidate
tags: catalog, stale-cache, failure-handling
applies-to: workflows requiring a live catalog before work
seen-in: public I2E catalog intake change 380fde5
updated: 2026-11-19
---

# Exercise a failed refresh after a successful intake

## Trigger

A startup or resume path can read a saved catalog when a remote fetch or catalog validation fails.

## Check

Prime a valid local snapshot. Make the remote unavailable and invoke the real intake again. Check that it stops before work, produces no new success receipt, and preserves the original snapshot. Repeat with a reachable remote that contains an invalid record.

## Why it flags

A local catalog can validate successfully while the remote is unreachable. The prior workflow allowed a cached revision to stand in for a current fetch. Testing with a primed cache catches that path.

## Cases

[Previous public intake instructions](https://github.com/bowang-solutionstream/i2e-team/blob/120fa668ec6b3bec493658d7bbe1ec16c1209bb9/README.md#read-the-latest-library) · [Failed-refresh regressions](https://github.com/bowang-solutionstream/i2e-team/blob/380fde5649388a0a254dcde9e0c2eb7c0897ef53/tests/test_library.py#L300)

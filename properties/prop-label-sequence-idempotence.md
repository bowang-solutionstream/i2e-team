---
id: prop-label-sequence-idempotence
kind: property
type: idempotency
status: adopted
tags: labels, sequence, idempotence
applies-to: label APIs that preserve sequence and input
seen-in: public label normalization pilot
updated: 2026-11-19
---

# Preserve the label sequence and stabilize after one normalization

## Statement

For a list-normalization API that promises to preserve positions, normalizing twice gives the same result as normalizing once. The first result has the input length and order, retains duplicates and leaves the caller's input unchanged.

## Example

Take a copy of a list with distinguishable endpoints and an internal duplicate. Call the public API, compare the original against its copy, check the expected result at every index, then apply the API to the result again.

## Notes

Check order and multiplicity separately from repeated application. A normalizer that sorts its input can still be idempotent. [Original property and oracle](https://github.com/bowang-solutionstream/i2e-team/blob/52d9d48b059c57f434bbd69863f1df4a9b04bfaf/skills/i2e-team/references/label-verification.json)

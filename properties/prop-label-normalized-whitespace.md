---
id: prop-label-normalized-whitespace
kind: property
type: equivalence
status: adopted
tags: labels, whitespace, normalization
applies-to: label APIs with whitespace-only normalization
seen-in: public label normalization pilot
updated: 2026-11-19
---

# Collapse whitespace without changing the known tokens

## Statement

For a label API whose contract trims and collapses whitespace, construct inputs by surrounding known non-whitespace tokens with generated whitespace runs. Its output must equal the original tokens joined with one ASCII space. The empty or all-whitespace label yields the empty string.

## Example

Generate empty, repeated and multilingual tokens and separate them with spaces, tabs, nonbreaking spaces and em spaces. Compute the expected text directly from the preselected tokens. Exercise the public API.

## Notes

This is an adopted check for the published label fixture. Reuse it where the product specifies the same whitespace contract. [Original property and oracle](https://github.com/bowang-solutionstream/i2e-team/blob/52d9d48b059c57f434bbd69863f1df4a9b04bfaf/skills/i2e-team/references/label-verification.json)

---
id: prop-moved-handler-answers-the-same
kind: property
type: equivalence
status: candidate
tags: http, refactor, api, differential
applies-to: request handlers moved into shared code
seen-in: a change adding saved test cases to rules and running them before release (2026-11)
updated: 2026-11-20
---

# A behaviour-preserving move answers every input as before

## Statement

When request handling moves into a shared function, the old and the new handler give the same status and the same body, byte for byte, for every input: valid ones and each kind of refusal. Differences approved in advance are listed and nothing else differs.

## Example

Run the same input set (every fixture entity crossed with every rule, with and without overrides, plus one input per refusal) through the base revision's handler and the candidate's, write both answer lists to files, and compare their digests.

## Notes

Inputs that depend on the clock must run on the same day; database-error paths may differ only in which error wins, if that is approved.

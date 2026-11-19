---
id: rule-label-preserve-unicode-spelling
kind: rule
type: test
status: candidate
tags: labels, unicode, normalization
applies-to: label APIs that change whitespace only
seen-in: public label pilot seeded Unicode transformation
updated: 2026-11-19
---

# Preserve non-whitespace Unicode code points

## Trigger

A change to a whitespace-only label normalizer introduces or changes a Unicode transformation.

## Check

Pass a decomposed accented letter and a compatibility character through the public API. Compare their output code points to the original sequence after only the specified whitespace changes.

## Why it flags

Canonical or compatibility normalization can silently change the spelling while leaving a visually similar label. The published label pilot caught this on a seeded fault and replayed its regression. It is one observed change for shared-rule adoption.

## Cases

[Published pilot rule and replay examples](https://github.com/bowang-solutionstream/i2e-team/blob/52d9d48b059c57f434bbd69863f1df4a9b04bfaf/skills/i2e-team/references/label-verification.json)

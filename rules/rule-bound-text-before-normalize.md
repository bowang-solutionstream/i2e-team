---
id: rule-bound-text-before-normalize
kind: rule
type: review
status: candidate
tags: unicode, denial-of-service, input-validation
applies-to: services that normalize caller text
seen-in: a change adding saved test cases to rules and running them before release (2026-11)
updated: 2026-11-20
---

# Bound caller text before Unicode normalization

## Trigger

Caller-controlled text reaches String.prototype.normalize (or another super-linear text routine) without a length cap ahead of it, including in startup or batch paths that read stored values.

## Check

A length cap (in code points) before the text is stored, and a bound inside the routine itself for stored or derived text; a timing check of the worst case (long runs of combining marks of alternating classes).

## Why it flags

NFC reorders combining marks quadratically: one 256 KiB name took about 4 s in Node 26 (ICU 79), blocking the only event loop for every request.

## Cases

A save route normalized test names of any length before checking anything else, under a row lock, and at startup.

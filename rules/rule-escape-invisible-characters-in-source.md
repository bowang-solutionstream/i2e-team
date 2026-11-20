---
id: rule-escape-invisible-characters-in-source
kind: rule
type: review
status: candidate
tags: unicode, source-code, tooling
applies-to: any
seen-in: a change adding saved test cases to rules and running them before release (2026-11)
updated: 2026-11-20
---

# Write invisible characters as escapes, never raw

## Trigger

A diff adds a raw invisible or direction-changing character to code, tests or documents, usually inside a string literal: a bidirectional override or isolate, a zero-width space or joiner, a Hangul filler, a soft hyphen, or another default-ignorable code point.

## Check

Such characters appear only as escapes in code (a backslash-u escape) and as code-point names in documents (U+202E). Scan every changed file for default-ignorable code points and bidirectional controls before review, and again after any tool rewrites a file.

## Why it flags

The character cannot be seen in review or in most editors, so a test may not test what it appears to; a bidirectional control can also make code read differently from how it runs.

## Cases

A file-writing tool turned backslash-u escapes in a test file into the raw characters they name; one raw right-to-left override stayed in a test's source until a scan found it.

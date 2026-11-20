---
id: rule-moved-call-meets-unguarded-input
kind: rule
type: review
status: candidate
tags: refactor, validation, error-handling, api
applies-to: any
seen-in: a change adding saved test cases to rules and running them before release (2026-11)
updated: 2026-11-20
---

# A call moved ahead of a check meets inputs it never saw

## Trigger

A change moves a call earlier, ahead of a check that used to stop the flow before it (for example, running a list before deciding a version can run at all).

## Check

List every input that used to stop at the check and now reaches the call; guard each, and add a test with one such input end to end.

## Why it flags

The moved call now meets malformed inputs the check used to stop, and an unguarded throw there turns a reasoned refusal into a server error.

## Cases

- A release check ran a version's tests before judging the version, and a wording helper threw on a node kind the engine does not know: a 500 where a 409 with reasons was due.
- Later in the same change, a trace cut added to every test run walked the whole tree with the same helper and brought the 500 back; a guard keeps the judged outcome and drops the path.

---
id: rule-written-claims-match-what-the-code-does
kind: rule
type: review
status: candidate
tags: docs, adr, api, ui-text
applies-to: any
seen-in: an AI change dialog with a line diff in a React and Base UI app (2026-11), a change adding saved test cases to rules and running them before release (2026-11)
updated: 2026-11-20
---

# Every claim in a document or on a screen matches what the code does

## Trigger

A decision record, spec, plan or API document in the diff says what another feature's screen or route does, or what a route refuses first (such as "401 otherwise"); or screen text states something about server state that can change after the page loaded (that a version is the newest), or contradicts a label beside it.

## Check

Open the other feature's code at the candidate and confirm each claim, or reword it to what the code does now. For error order, check the framework's request lifecycle (many parse the body before route guards, so a large or malformed body gets 413 or 400 before 401) and pin the real order with a signed-out test. For screen text, walk each state the view can be in, including another user's save meanwhile, and reword to what holds in all of them.

## Why it flags

Approvers, clients and users act on the written words: a decision record can describe risks that do not exist yet or hide ones that do, clients are surprised by the real first error, and the page tells people things that are false.

## Cases

- A route document promised 401 first; the framework answered 413 for a body over its limit and 400 for one that was not JSON, before the user guard ran.
- "Runs on version N, the newest saved version" became "This page shows version N; runs use the newest saved version", and a hidden result for another version reads "Ran on version N", not "Not run".

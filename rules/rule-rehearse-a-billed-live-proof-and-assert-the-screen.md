---
id: rule-rehearse-a-billed-live-proof-and-assert-the-screen
kind: rule
type: blind-spot
status: candidate
tags: e2e, external-calls, evidence, cost
applies-to: proofs that make live, billed or limited requests
seen-in: an AI change dialog with a line diff in a React and Base UI app (2026-11)
updated: 2026-11-20
---

# A live, billed proof is rehearsed where nothing is spent and asserts what the person saw

## Trigger

Acceptance needs a live run that sends a request costing money or coming from a small allowance, such as a live model call with the developer's key, through a script written or changed for that step.

## Check

Run the same script first against a stack that answers without spending (prepared answers, a stub, no key) and make it pass there, asserting the steps up to and including the request being sent once. In the live run, assert the screen, and that the answer was not a fallback, rather than relying on server log lines; keep the trace and a screenshot, never a key.

## Why it flags

A script error found during the billed run spends the request and proves nothing, and the allowance may not cover a second try. Server log lines read the same whether or not the result reached the screen.

## Cases

The dry run found a quoting error that kept the script from parsing, then a click on a button below the window's fold that sent no request; both were fixed before the one live request, which then passed.

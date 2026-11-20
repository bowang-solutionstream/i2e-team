---
id: rule-check-every-answer-shape-the-producer-sends
kind: rule
type: review
status: candidate
tags: validation, fetch, ui-state, fixtures, tests
applies-to: clients that read API or producer answers
seen-in: an AI change dialog with a line diff in a React and Base UI app (2026-11), a change adding saved test cases to rules and running them before release (2026-11)
updated: 2026-11-20
---

# A client checks each answer shape the producer can send, no more strictly than its view needs

## Trigger

A client reads fields of an answer in `promise.then(onSuccess, onError)` where the answer may be null or the wrong shape; a shape check is added in front of a view that already handles some malformed parts itself; or test helpers build answers in one shape, or code that rewrites a producer's messages is tested on a few of its variants.

## Check

List every shape the real producer can return (problems with and without a parsed result, each message template, found by searching its code) and give each a test, including a 2xx answer that is not JSON, one of the wrong shape, and a list holding a null. Check the shape in a step before the success handler (`.then(parse).then(onSuccess, onError)`) so a bad answer reaches onError, and ask each item only for the fields the view reads without a guard of its own; then run the view's existing tests for its designed partial states.

## Why it flags

A throw inside onSuccess becomes an unhandled rejection, not a call to onError, so the screen waits for ever on "Loading" with its buttons disabled. An over-strict check turns a designed partial display into a whole failure, and a guard needed only for a shape no fixture builds can be deleted with every test green.

## Cases

- A tab read `data.items` in the success handler; a 200 answer with no readable body left it on "Loading..." with Run disabled. Items that were objects but lacked the fields the view reads then passed a check that only asked for objects.
- A result check also required the trace to be a list, though the tab was built to show such a result with "this answer cannot be drawn".
- A dialog's tests built problem responses only without a parsed result; a repair that capitalised a rule engine's messages was tested on three of them, and one template begins with a lookup's name, which then read as a different word.

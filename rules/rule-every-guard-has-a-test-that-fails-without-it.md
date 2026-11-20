---
id: rule-every-guard-has-a-test-that-fails-without-it
kind: rule
type: test
status: candidate
tags: tests, mutation-testing, guards, fixtures, ui
applies-to: any
seen-in: an AI change dialog with a line diff in a React and Base UI app (2026-11), a change adding saved test cases to rules and running them before release (2026-11)
updated: 2026-11-20
---

# Every guard has a test that fails without it

## Trigger

A handler or effect returns early on a flag (aborted, unmounted, closed, already running, or one term of a compound condition such as "valid"); an action resets state at its start (clearing the last answer when a new request starts); or a test asserts that something does not happen (focus taken, a request sent, an input changed).

## Check

Remove each guard, or each term of a compound guard, in a scratch copy and confirm a named test fails on its assertion; where two guards cover the same path, remove both. If the guard's test still passes, move it to a state the environment can fail (jsdom never focuses inside a hidden panel, so use a visible element or a real request) and break it again. Run the whole test file, not only the guard's test, with fixtures that hand out deep copies. Keep each break's diff and log.

## Why it flags

Tests written from the happy path rarely reach the second guard on a path. A guard whose scenario the environment cannot produce, or whose shared fixture an earlier test changed, passes on broken code, and a record can name the wrong break as a guard's proof.

## Cases

- A stopped request's failure path, an abort on unmount, a double press, a closing-frame press, and a "no problems" term that only one fixture shape reached. A human review then found that clearing the previous answer at the start of Ask again had no test: with that reset deleted, the whole front-end suite still passed, so a stale answer could have stayed beside the progress message after the new request failed.
- A "a later tab takes no focus" guard used a tab started out of sight, so breaking the guarded code was missed; rewritten to a visible restart, it caught the break.

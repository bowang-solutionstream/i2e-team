---
id: rule-a-test-depends-only-on-what-it-controls
kind: rule
type: test
status: candidate
tags: tests, flaky-tests, e2e, timing, harness
applies-to: any
seen-in: a change adding saved test cases to rules and running them before release (2026-11), an AI change dialog with a line diff in a React and Base UI app (2026-11), an earlier change adding generated sample records (2026-11)
updated: 2026-11-20
---

# A test's result depends only on what the test controls

## Trigger

A test asserts an order by creation time without setting the times; starts an in-process database (for example PGlite, which compiles WebAssembly) inside its own body; waits for a navigation or load and then clicks by text or position; or asserts the total number of requests a page made around a step that shows other components.

## Check

- Stamp explicit, increasing times, and test the tie-break for equal times separately.
- Start the database once in beforeAll or the runner's setup, so no test's timeout includes the first compile.
- Wait for an element only the destination has, and have page evaluations return plain values, never DOM nodes.
- Count only the requests to the endpoints of the component under test, by method and path.

## Why it flags

Each test then fails at random or passes for the wrong reason: two quick inserts share a clock value, a loaded machine pushes the first compile past a 5 s timeout, a wait the old page satisfies lets the driver click where an element used to be, and other components' requests change the total.

## Cases

- Six rows inserted in a row on an in-process database got equal times, and the name tie-break reordered them.
- Two tests timed out in full runs (6.6 s and 5.1 s) that took well under a second alone; one was written in an earlier change.
- A count of requests on a failed tab included the History tab's own lists, loaded when the test left.

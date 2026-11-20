---
id: rule-every-request-a-screen-waits-on-can-end
kind: rule
type: review
status: candidate
tags: ui, async, network, timeout, resilience
applies-to: web UIs that wait on requests
seen-in: an AI change dialog with a line diff in a React and Base UI app (2026-11), a change adding saved test cases to rules and running them before release (2026-11)
updated: 2026-11-20
---

# Every request a screen waits on can end

## Trigger

A screen or dialog shows "Loading" or "Running", turns its buttons off, or refuses to close until a request settles, and the request has no time limit (the client helper takes no signal, the server sets no request timeout); or an effect starts a request and its cleanup only sets a flag.

## Check

A time limit aborts the request and the screen says what may have happened, with Try again or a control that gives the request up; race the request against the timer so the limit holds even when the transport ignores the abort. Cleanup aborts the request: one AbortController per effect run, passed to the fetch helper and chained with the time limit. Test with fake timers and a request that never settles, unmount while one is held, and walk it once in a real browser with the server held (for example by a table lock).

## Why it flags

A lock is written for the request that answers. A dropped connection or a database that does not answer leaves the screen waiting with its main action off until a reload, and a request nobody waits for keeps spending server work.

## Cases

- A save with no time limit locked a dialog; it is now given up after 30 seconds, with "the change may not have been saved".
- A tests tab's list and run requests had no limit: a run held by a table lock stayed on "Running..." until a one-minute limit, an abort and Try again were added, and the requests ran on after the page was left.

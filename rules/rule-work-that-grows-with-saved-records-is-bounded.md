---
id: rule-work-that-grows-with-saved-records-is-bounded
kind: rule
type: review
status: candidate
tags: performance, caching, database, read-path
applies-to: services whose stored records users can add
seen-in: a change adding saved test cases to rules and running them before release (2026-11)
updated: 2026-11-20
---

# Work that grows with what users saved is cached or bounded

## Trigger

A read route behind a landing page or dashboard tile, or a loop over stored records, runs work per record (an evaluation, a test run, an external call) or reads the same shared data (reference tables, configuration) for each record, especially inside a transaction or for records users can add and nobody can remove.

## Check

The read is cached with a key that covers every input of the work, or bounded, and reads that arrive together share one computation; a loop reads shared data once per distinct key and gives each record its own copy when the callee writes into it. Test that a second read with nothing changed runs no work and that each input change reruns only what it touches, and count queries with a logger on the test database. The properties prop-cached-aggregate-matches-a-fresh-computation and prop-once-per-key-loader-matches-fresh-reads are the oracles.

## Why it flags

Records saved by anyone, once, make every later page view slower for every user, a transaction stays open the whole time, and the cost stays after whoever added them has gone.

## Cases

- A dashboard's "tests passing" count ran every stored test case of every rule on each read; a security review blocked it, and a per-rule count keyed by what the tests are judged on fixed it.
- A test run and the release check read every reference row once per test case; a per-date loader handing out deep copies cut it to one read per date.

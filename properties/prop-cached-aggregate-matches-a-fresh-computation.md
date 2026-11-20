---
id: prop-cached-aggregate-matches-a-fresh-computation
kind: property
type: equivalence
status: candidate
tags: cache, aggregate, concurrency, read-path
applies-to: aggregates cached between reads
seen-in: a change adding saved test cases to rules and running them before release (2026-11)
updated: 2026-11-20
---

# A cached aggregate matches a fresh computation, and no read gets an answer older than itself

## Statement

After every sequence of writes the system can make, an aggregate kept between reads (a count, a total, a summary) equals the same aggregate computed from scratch on the same data. For the computation behind it, at most one runs per store at any moment and at most one more waits, and every read's answer comes from a computation that began after the read arrived, so a read never misses a write that finished before it.

## Example

- Step through each kind of write in turn (a new child record, a new version of a parent, new reference data, a new day, a new parent), and after each step assert that the kept answer and a from-scratch computation both equal the step's expected numbers. Pin the expected numbers too, so a step that changes nothing is not mistaken for agreement.
- Hold the running computation at its first step (a gate in a wrapped dependency), make a write, start a second read, release the gate: the first read may answer without the write, the second must include it, and the number of underlying runs equals one full run plus one recount of what changed. Also register a read on the running computation's own promise, so it lands between that computation's end and the queued one's start.

## Notes

- It proves the cache key covers every input a write can change; one deliberate break per key part shows each part is needed. It does not cover writes made outside the application, such as a hand-run update.
- A read that joins the running computation instead (plain single-flight) can answer from before a write it follows.

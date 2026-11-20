---
id: rule-pools-handle-connection-errors
kind: rule
type: review
status: candidate
tags: database, resilience, node
applies-to: Node.js services with database connection pools
seen-in: a change adding saved test cases to rules and running them before release (2026-11)
updated: 2026-11-20
---

# A long-lived connection pool handles its errors

## Trigger

A server creates a database pool (for example a node-postgres Pool) and never listens for its error event.

## Check

The pool has an error listener that logs and keeps the process up. In a walk, stop and start the database: the service answers errors meanwhile and recovers without a restart.

## Why it flags

An idle client's lost connection is raised on the pool; with no listener the process exits, so a database restart takes the service down.

## Cases

Seen in a walk: stopping Postgres made the API exit. The code was older than the change being walked, so it was reported, not fixed there.

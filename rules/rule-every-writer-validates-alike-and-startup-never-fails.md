---
id: rule-every-writer-validates-alike-and-startup-never-fails
kind: rule
type: review
status: candidate
tags: validation, seed, import, startup, data-integrity
applies-to: services with seeds, importers or start-up data steps
seen-in: a change adding saved test cases to rules and running them before release (2026-11)
updated: 2026-11-20
---

# Every writer runs the same validation, and start-up never fails on data users can change

## Trigger

A table gets rows from more than one writer (a route and a seed, a top-up or an importer) and the diff adds or changes the route's checks; or code that runs before a server listens (a seed top-up, a data migration, a cache warm-up) checks rows users can change and throws when the check refuses.

## Check

All writers call one shared validation function. Each acts on a refusal as its context needs: an error for a request, a stop for a fresh load the repository controls, and a skip with a warning naming what and why for a top-up on a database loaded earlier, with the rest of that step still committed. Test a refused row through each writer, and restart a real container on data a user changed.

## Why it flags

A row the route would refuse arrives by the other path and fails later, far from its cause. A start-up step that throws on user data restarts a hosted service into the same failure, and only a code change gets it out.

## Cases

- A seed checked only test names and input files; a typo in an expected outcome would have been stored and failed every run of its rule.
- A seed top-up began checking each demo test case against its rule's newest version and threw on a refusal, so once a user changed a demo rule the API would not start, and the reference top-up in the same transaction rolled back. A fix for one review introduced it, and the next review caught it.

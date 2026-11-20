---
id: rule-hold-the-page-until-it-reads-its-write
kind: rule
type: review
status: candidate
tags: ui, async, data-fetching, concurrency
applies-to: web UIs whose data hooks keep the last answer while reloading
seen-in: an AI change dialog with a line diff in a React and Base UI app (2026-11)
updated: 2026-11-20
---

# A write holds the page's other writers until the page has read it

## Trigger

A screen writes, then reads its data again, and its data hook keeps the old answer on screen until the new one arrives, while other controls on the screen can write from that old answer.

## Check

For each write path, list what else on the page can write before the reload lands. Hold the reload in a test, and in a real browser by holding the request, and try each one. Every write path needs the same hold, not only the one written first.

## Why it flags

Reviews read each write path alone. The window between a write and the page's reload belongs to no single component, and the first path's hold (an editor kept in its saving state until it is replaced) is easy to miss when a second path is added.

## Cases

After an accepted AI change, the Rule tab stayed editable on the old version until the reload landed, so a save of that text would have undone the change with no conflict raised. The manual save already held its editor. Found by a human reviewer after seven AI review rounds.

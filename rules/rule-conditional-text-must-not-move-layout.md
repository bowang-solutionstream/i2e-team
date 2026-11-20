---
id: rule-conditional-text-must-not-move-layout
kind: rule
type: blind-spot
status: candidate
tags: ui, layout, css
applies-to: web UIs
seen-in: an AI change dialog with a line diff in a React and Base UI app (2026-11)
updated: 2026-11-20
---

# Text that appears on a condition does not move the page

## Trigger

A hint, notice or error line is added or lengthened in a header or toolbar column that sizes to its content.

## Check

In a scripted run, measure a landmark below it (an editor's top) before the text appears, while it shows, and after it goes; they must be equal. Constrain the line to the column's width (for example w-0 min-w-full).

## Why it flags

A longer line widens its column, wraps its neighbour and shifts everything below on the first keystroke.

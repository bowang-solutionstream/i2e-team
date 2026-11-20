---
id: rule-reopen-during-close-gets-fresh-form
kind: rule
type: blind-spot
status: candidate
tags: ui, dialog, state
applies-to: web UIs with animated dialogs that hold form state
seen-in: an AI change dialog with a line diff in a React and Base UI app (2026-11)
updated: 2026-11-20
---

# A dialog reopened while it is still closing starts fresh

## Trigger

A dialog component kept mounted during its closing animation holds form state, and something on the page can set it open again (a button outside the dialog).

## Check

Close the dialog and press the opener before the close ends, with input that skips the overlay (a script click, or assistive technology). The reopened dialog must start empty, not show the last opening's text, message or "working" state. Key the form by an opening count.

## Why it flags

The dialog library reuses the closing popup, so the same form instance keeps its state; a mouse cannot reach the opener (the overlay takes the click) but other input can.

## Cases

Found by a browser walk after two doubt reviews judged it unreachable from the source.

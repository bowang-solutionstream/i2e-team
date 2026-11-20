---
id: rule-keyboard-and-touch-users-keep-focus-and-information
kind: rule
type: blind-spot
status: candidate
tags: ui, accessibility, keyboard, focus, touch
applies-to: web UIs
seen-in: a change adding saved test cases to rules and running them before release (2026-11)
updated: 2026-11-20
---

# Keyboard and touch users keep their focus and see every piece of information

## Trigger

A button's own press turns it off (native disabled), hides it, or replaces the region it is in (a loading state, or a component started again by a new key); or meaningful text is put only in a title attribute, especially on an element that cannot take focus.

## Check

After each such action, focus sits on something stable: the same button kept focusable while off (aria-disabled, for example Base UI's focusableWhenDisabled), the next useful control, or a status line with tabIndex -1; across a restart by key, the new instance is told to take focus once. Show title-only text as text, or behind a control that keyboard and touch can open. Test document.activeElement after each action and that no element keeps a title holding the text, and walk the screen from the keyboard in a real browser: jsdom does not move focus off a control that turns disabled.

## Why it flags

A keyboard user lands on the page body and the next Tab starts again at the top, and keyboard and touch users never see a title tooltip.

## Cases

- A tests tab lost focus on Run, on Try again, on Look again, and on Show version, which started the tab again for another version.
- An executed path's steps kept their rule wording in a title only; it is now a line of text under each step whose words do not already say it.

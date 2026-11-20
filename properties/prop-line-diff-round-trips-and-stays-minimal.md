---
id: prop-line-diff-round-trips-and-stays-minimal
kind: property
type: round-trip
status: candidate
tags: diff, text, ui
applies-to: line diff functions
seen-in: an AI change dialog with a line diff in a React and Base UI app (2026-11)
updated: 2026-11-20
---

# A line diff gives back both texts, marks no line it need not, and lists removals first

## Statement

For any two texts:

- the unchanged and removed lines of their line diff, in order, are the lines of the first text, and the unchanged and added lines, in order, are the lines of the second;
- the number of unchanged lines equals the length of the longest common subsequence of the two texts' lines;
- between two unchanged lines, no removed line follows an added line.

## Example

Generate pairs of short texts from a few repeated line values (blank lines, near-duplicates, both kinds of line break, with and without a final break). Compare each side of the diff with the lines the generator wrote, not with a re-split of the text, so the test does not share the code's own line splitting. For texts of at most about seven lines, compute the longest common subsequence by brute force over every subsequence of one side.

## Notes

- Seed the generator and record the seed and run count. Breaking the final-line-break rule fails the first clause at once, a greedy matcher fails the second within a few pairs, and preferring addition on a tie breaks the third.
- No clause pins which of several equally long matches is chosen; keep an example test for that.

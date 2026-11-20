---
id: prop-plain-words-normalizer
kind: property
type: idempotency
status: candidate
tags: unicode, normalization, names, text
applies-to: text normalizers that remove characters and compose
seen-in: a change adding saved test cases to rules and running them before release (2026-11)
updated: 2026-11-20
---

# A plain-words normalizer is idempotent and keeps what shows

## Statement

For a normalizer that drops default-ignorable characters, reads each run of whitespace and control characters as one space, trims, and then composes (NFC), for every string s:

- normalize(normalize(s)) equals normalize(s);
- normalize(s) is in NFC, holds no default-ignorable or control character, and has no space at either end and never two in a row;
- putting a default-ignorable character between any two characters of s does not change normalize(s);
- for visible words joined by single spaces, normalize(s) equals s in NFC.

## Example

```ts
fc.assert(fc.property(fc.string({ unit: 'grapheme' }), (s) => normalize(normalize(s)) === normalize(s)));
fc.assert(fc.property(fc.string({ unit: 'grapheme' }), (s) => normalize(s) === normalize(s).normalize('NFC')));
```

## Notes

- Generate from a curated alphabet as well (combining marks of different classes, zero-width characters, Hangul fillers, emoji joined by a zero-width joiner, surrogate pairs); random strings rarely put an ignorable character between a letter and its mark.
- Insert at code-point boundaries, never inside a surrogate pair.
- Only the last clause catches a normalizer that drops visible text; the others hold for one that returns "".
- Remove and collapse first, compose last. Composing first broke idempotency in the change behind this entry: a removed character that sat between a letter and its mark left them uncomposed, so two names that look alike compared different.

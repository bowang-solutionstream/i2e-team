---
id: prop-once-per-key-loader-matches-fresh-reads
kind: property
type: equivalence
status: candidate
tags: caching, memoization, mutation, evaluation
applies-to: code that shares reads across the items of one run
seen-in: a change adding saved test cases to rules and running them before release (2026-11)
updated: 2026-11-20
---

# A once-per-key loader loads each key once, hands out independent copies, and changes no result

## Statement

For any sequence of calls, concurrent ones included, the underlying load runs once per distinct key, every call returns a value equal to what was loaded for its key, and changing a returned value, nested values included, never changes what a later call returns. Evaluating a sequence of items through the loader, each item with optional overrides written into the data it is given, gives the same results as evaluating each item with its own fresh read.

## Example

```ts
fc.assert(fc.asyncProperty(fc.array(fc.constantFrom('a', 'b', 'c'), { minLength: 1 }), async (keys) => {
  const loads: string[] = [];
  const get = oncePerKey(async (k: string) => { loads.push(k); return { rows: [{ k }] }; });
  for (const k of keys) {
    const v = await get(k);
    expect(v).toEqual({ rows: [{ k }] });
    v.rows[0].k = 'changed';   // a caller writes into its copy
  }
  expect(loads).toEqual([...new Set(keys)]);
}));
```

For the equivalence, one example pinned it in the change behind this entry (an item that replaced a source, followed by one that relied on the stored source); a generated sequence of items and overrides would cover what one example cannot.

## Notes

A copy of the top level only fails the nested-change part; that was broken on purpose and caught.

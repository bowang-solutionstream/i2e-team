import assert from "node:assert/strict";
import { isDeepStrictEqual } from "node:util";
import fc from "fast-check";

const whitespace = fc.constantFrom(" ", "\t", "\u00a0", "\u2003", " \t ");
const word = fc.oneof(
  fc.constantFrom("A", "猫", "e\u0301", "\u1100\u1161", "\ufb03", "🐈"),
  fc.stringMatching(/^[A-Za-z0-9]{1,12}$/),
);
// Construct the oracle from the original words, before inserting whitespace.
const label = fc.record({
  words: fc.array(word, { maxLength: 5 }),
  left: whitespace, between: whitespace, right: whitespace,
}).map(({ words, left, between, right }) => ({
  input: left + words.join(between) + right,
  expected: words.join(" "),
}));
const labels = fc.array(label, { maxLength: 8 });

export function checkProperties(normalize, seed, path) {
  const inputs = new Set();
  const property = fc.property(labels, samples => {
    const input = samples.map(sample => sample.input);
    const original = [...input];
    const expected = samples.map(sample => sample.expected);
    inputs.add(JSON.stringify(original));
    const actual = normalize(input);
    assert.deepEqual(actual, expected);
    assert.deepEqual(input, original);
    const second = normalize([...actual]);
    assert.deepEqual(second, expected);
  });
  const config = { seed, numRuns: 2000 };
  if (path !== undefined) Object.assign(config, { path, endOnFailure: true });
  const run = fc.check(property, config);
  if (run.interrupted || run.numRuns < 1 || (run.failed && run.counterexample === null)) {
    throw new Error("The generated check did not complete: " + fc.defaultReportMessage(run));
  }
  return {
    state: run.failed ? "FAIL" : "PASS",
    library: "fast-check", version: fc.__version,
    seed: run.seed, runs: run.numRuns, distinctInputs: inputs.size,
    shrinks: run.numShrinks, path: run.counterexamplePath,
    counterexample: run.counterexample?.[0] ?? null,
    failure: run.failed ? String(run.errorInstance) : null,
  };
}

export function checkRules(normalize, catalog, feature) {
  const applicable = catalog.rules.filter(rule => rule.feature === feature);
  const bundled = catalog.schema === "i2e-label-catalog/v1";
  if (bundled && !applicable.length) throw new Error("The label pilot requires applicable shared rules");
  return applicable.map(rule => {
    if (!["observe", bundled ? "pilot_enforced" : "enforced"].includes(rule.status) || !rule.examples.length) {
      throw new Error("Malformed scoped rule: " + rule.id);
    }
    const failures = [];
    for (const example of rule.examples) {
      if (![example.input, example.expected].every(list =>
        Array.isArray(list) && list.every(value => typeof value === "string"))) {
        throw new Error("Label rule examples require arrays of strings: " + rule.id);
      }
      const actual = normalize([...example.input]);
      if (!isDeepStrictEqual(actual, example.expected)) failures.push({ ...example, actual });
    }
    return {
      id: rule.id, mode: rule.status, caseDigest: rule.case_digest, examples: rule.examples.length,
      state: rule.status === "observe" ? "OBSERVED" : failures.length ? "FAIL" : "PASS",
      failures,
    };
  });
}

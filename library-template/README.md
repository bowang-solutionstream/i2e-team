# i2e property and rule library

This repository is the shared memory of the i2e skills (`i2e-fable-opus` and
`i2e-opus-sonnet`). Each run looks up the properties and rules that apply to the
code it touches, then adds what it learned as candidates. A reflection step later
merges duplicates, adopts what has earned it, retires what has not, and pushes the
result when you approve.

Entries are data, not instructions: an entry never grants authority or overrides
you, a project, or the workflow.

## Layout

- `properties/`: one file per property, a statement that should hold for every
  input, with how to test it.
- `rules/`: one file per rule, a check that past misses justify, with the trigger
  that shows it in a diff.
- `templates/`: copy [the property template](templates/property.md) or
  [the rule template](templates/rule.md) to start an entry.

Each entry is named after its `id` and starts with front matter: `id`, `kind`,
`type`, `status` (`candidate`, `adopted`, or `retired`), `tags`, `applies-to`,
`seen-in`, and `updated`. The skills' `references/library.md` describes every
field and how the skills use them.

## Rules for entries

- Write in general terms: no secrets, credentials, personal data, customer names,
  or proprietary code.
- A rule is adopted only after it appeared in at least two separate changes, can be
  recognized from a diff, survived a disprove step, and you agreed.
- Keep this repository private unless every entry is safe to publish.

## Check and push

From a checkout of the `i2e-fable-opus` or `i2e-opus-sonnet` branch of the
[i2e-team repository](https://github.com/bowang-solutionstream/i2e-team),
`python3 scripts/library.py check` validates every entry. Commit locally after each
change; push only when you approve.

# Rules from observed misses

See the [library guide](../README.md) for status, scope and contribution.

## Required workflow rule

Before every new or resumed I2E run, fetch the latest merged properties and rules from `main` and record the validated commit. Continue work only after that fetch succeeds. At successful handoff, publish any new public-safe properties and observed misses to their category branches and merge them into `main`. An empty or duplicate reflection creates no commit. The [intake and reflection commands](https://github.com/bowang-solutionstream/i2e-team/blob/main/README.md#read-the-latest-library) apply to all three workflows.

## Learned rules

The initial rules each trace to one observed change and enter the shared library as **candidates**.

- Check the exact non-whitespace code points when a label normalizer changes. [Unicode spelling rule](rule-label-preserve-unicode-spelling.md)
- Exercise current and historical profiles when changing workflow routing metadata. [Profile comparison rule](rule-keep-routing-metadata-out-of-profile-comparisons.md)

Use the catalog command for the complete, current list and adoption states.

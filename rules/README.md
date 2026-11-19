# Rules from observed misses

See the [library guide](../README.md) for status, scope and contribution.

The initial rules each trace to one observed change and enter the shared library as **candidates**.

- Check the exact non-whitespace code points when a label normalizer changes. [Unicode spelling rule](rule-label-preserve-unicode-spelling.md)
- Exercise current and historical profiles when changing workflow routing metadata. [Profile comparison rule](rule-keep-routing-metadata-out-of-profile-comparisons.md)

Use the catalog command for the complete, current list and adoption states.

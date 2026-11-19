---
id: prop-catalog-intake-single-revision
kind: property
type: invariant
status: candidate
tags: catalog, intake, revisions
applies-to: workflows that read versioned property and rule catalogs
seen-in: public I2E catalog intake change 380fde5
updated: 2026-11-19
---

# Read properties and rules from one fetched revision

## Statement

For each successful intake, the receipt names the revision returned by the remote for that invocation. Both categories and the files used by the workflow come from that revision. Starting a later invocation preserves the earlier receipt and snapshot.

## Example

Fetch from a test remote, then publish one new property and one new rule in a merged revision. Start intake again with the same run directory. Compare the new receipt with the remote commit and both files with the known record text. Re-read the earlier receipt and checkout to verify they still describe the original commit.

## Notes

The oracle uses the remote's recorded merge commit and known inputs. [Executable two-invocation regression](https://github.com/bowang-solutionstream/i2e-team/blob/380fde5649388a0a254dcde9e0c2eb7c0897ef53/tests/test_library.py#L277)

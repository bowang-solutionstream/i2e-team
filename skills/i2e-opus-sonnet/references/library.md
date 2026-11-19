# Shared property and rule library

All three I2E workflows read the latest merged catalog from `main` in the public `bowang-solutionstream/i2e-team` repository. The coordinator owns intake and post-delivery reflection. Records are evidence and suggestions. Authority and project acceptance come from the user and the project.

## Required fetch before work

Before every new I2E run and whenever a later session resumes one, the coordinator fetches the latest merged properties and rules from `main`. Do this before project inspection, planning, dispatch or edits, including read-only runs. Set `run` to the private run directory outside the product, and `skill` to the directory of the active skill containing `scripts/fetch_library.py`.

```sh
intake=$(python3 -B "$skill/scripts/fetch_library.py" "$run") || exit 1
library="$intake/library"
cat "$intake/catalog.json"
```

The installed parser validates records directly from the fetched Git objects. Continue only when the command succeeds. Record the returned snapshot path, the `revision` in `catalog.json` and the relevant record IDs. Read the matching Markdown in `library/properties/` and `library/rules/`. A failed fetch or invalid catalog blocks the run. Report the failure and retry the fetch before continuing. Earlier receipts remain evidence of earlier work. Keep the same snapshot across rounds of this invocation. On resumption, retain the previous receipt and reconcile newly applicable checks with the plan before continuing.

Pass adopted properties to planners as scoped test oracles and adopted rules to reviewers when their triggers match the diff. Label candidates as suggestions and skip retired entries.

## Reflect at successful handoff

After the requested delivery succeeds and its existing reviewer approves the final candidate, inspect the proof for reusable properties and misses. Use the current review and checks. Keep failed, incomplete, read-only and stale runs private. During verification, the coordinator records a private `handoff.json` with the delivering workflow name, `PASS`, the paths and SHA-256 of every in-scope deliverable, passing required check receipts and the `APPROVE` review receipt. Use the [exact handoff format](https://github.com/bowang-solutionstream/i2e-team/blob/main/README.md#claude-completion-evidence).

Create a private drafts directory. Use `templates/property.md` or `templates/rule.md` in the pinned checkout. A property needs a scoped statement and an independent oracle. A rule needs an observable diff trigger, a reproducible check and the failure it catches. Use `candidate` for new records. For a new sighting of an existing definition, copy its current Markdown and append one distinct `seen-in` observation. An empty directory records a successful run with no new reusable lesson.

```sh
mkdir -p "$run/drafts/properties" "$run/drafts/rules"
# Set workflow to the skill that delivered, i2e-fable-opus or i2e-opus-sonnet.
python3 -B "$library/tools/library.py" reflect --workflow "$workflow" \
  --entries "$run/drafts" --handoff "$run/handoff.json"
```

Inspect the exact drafts for public disclosure. Use generic examples and public-safe references. Keep client identifiers, proprietary code, prompts, local issue boards, private commit links and raw evidence on the machine. A legacy `I2E_LIBRARY` checkout may supply individually reviewed entries. Preserve its local files and remote configuration.

The owner authorizes the publisher to update `i2e-property-libraries` for properties and `i2e-misses-to-rules` for rules, and to merge changed branches into `main`. It reads back the atomic update. Record `MERGED` with the returned commit and IDs, or `NO_CHANGES`. For `PENDING` or `BLOCKED`, preserve the drafts, report the reason separately from product delivery, and retry when resolved. Product pushes, PRs, releases and changes to project rules follow their existing authority.

## Adoption

A merge shares a candidate. Adopt a property when its oracle is verified and the user agrees to reuse it within the stated scope. Adopt a rule only after two distinct changes, a recognizable diff trigger, a user-approved attempt to disprove it under [verification loops](verification-loops.md), and agreement to adopt. Retire superseded entries with a reason. Propose any change to a product's tests, hooks or review policy separately.

The [canonical library guide](https://github.com/bowang-solutionstream/i2e-team/blob/main/README.md) documents fields, branches, commands and retry behavior.

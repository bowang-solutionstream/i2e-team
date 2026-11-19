# Shared property and rule library

All three I2E workflows read the latest merged catalog from `main` in the public `bowang-solutionstream/i2e-team` repository. The coordinator owns intake and post-delivery reflection. Records are evidence and suggestions. Authority and project acceptance come from the user and the project.

## Pin the catalog at intake

Set `run` to this session's private directory outside the product checkout. For each new run:

```sh
git clone --quiet --single-branch --branch main https://github.com/bowang-solutionstream/i2e-team.git "$run/library"
python3 -B "$run/library/tools/library.py" catalog
```

Record the returned revision and the matching IDs. Share scoped adopted properties with the planner as test oracles and adopted rules with reviewers when their triggers match. Label candidate hints as such. Ignore retired records during selection. Resume against the pinned revision. If the fetch fails, record the known revision and its age, or mark the lookup unavailable.

## Reflect at successful handoff

After the requested delivery succeeds and its existing reviewer approves the final candidate, inspect the proof for reusable properties and misses. Use the current review and checks. Keep failed, incomplete, read-only and stale runs private. During verification, the coordinator records a private `handoff.json` with the delivering workflow name, `PASS`, the paths and SHA-256 of every in-scope deliverable, passing required check receipts and the `APPROVE` review receipt. Use the [exact handoff format](https://github.com/bowang-solutionstream/i2e-team/blob/main/README.md#claude-completion-evidence).

Create a private drafts directory. Use `templates/property.md` or `templates/rule.md` in the pinned checkout. A property needs a scoped statement and an independent oracle. A rule needs an observable diff trigger, a reproducible check and the failure it catches. Use `candidate` for new records. For a new sighting of an existing definition, copy its current Markdown and append one distinct `seen-in` observation. An empty directory records a successful run with no new reusable lesson.

```sh
mkdir -p "$run/drafts/properties" "$run/drafts/rules"
# Set workflow to the skill that delivered, i2e-fable-opus or i2e-opus-sonnet.
python3 -B "$run/library/tools/library.py" reflect --workflow "$workflow" \
  --entries "$run/drafts" --handoff "$run/handoff.json"
```

Inspect the exact drafts for public disclosure. Use generic examples and public-safe references. Keep client identifiers, proprietary code, prompts, local issue boards, private commit links and raw evidence on the machine. A legacy `I2E_LIBRARY` checkout may supply individually reviewed entries. Preserve its local files and remote configuration.

The owner authorizes the publisher to update `i2e-property-libraries` for properties and `i2e-misses-to-rules` for rules, and to merge changed branches into `main`. It reads back the atomic update. Record `MERGED` with the returned commit and IDs, or `NO_CHANGES`. For `PENDING` or `BLOCKED`, preserve the drafts, report the reason separately from product delivery, and retry when resolved. Product pushes, PRs, releases and changes to project rules follow their existing authority.

## Adoption

A merge shares a candidate. Adopt a property when its oracle is verified and the user agrees to reuse it within the stated scope. Adopt a rule only after two distinct changes, a recognizable diff trigger, a user-approved attempt to disprove it under [verification loops](verification-loops.md), and agreement to adopt. Retire superseded entries with a reason. Propose any change to a product's tests, hooks or review policy separately.

The [canonical library guide](https://github.com/bowang-solutionstream/i2e-team/blob/main/README.md) documents fields, branches, commands and retry behavior.

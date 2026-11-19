# I2E shared properties and rules

All three I2E workflows read this branch at intake. A **property** describes behavior that must hold across a defined input domain and gives an independent way to check it. A **miss-to-rule** records the change that should trigger a check, the check itself and the failure it would catch.

| Branch | Contents |
| --- | --- |
| [main](https://github.com/bowang-solutionstream/i2e-team/tree/main) | Latest merged catalog and reflection tool |
| [i2e-property-libraries](https://github.com/bowang-solutionstream/i2e-team/tree/i2e-property-libraries/properties) | Property records and their history |
| [i2e-misses-to-rules](https://github.com/bowang-solutionstream/i2e-team/tree/i2e-misses-to-rules/rules) | Rules learned from observed build misses |
| [i2e-astra-sol](https://github.com/bowang-solutionstream/i2e-team/tree/i2e-astra-sol) | Codex · `$i2e-astra-sol <task>` |
| [i2e-fable-opus](https://github.com/bowang-solutionstream/i2e-team/tree/i2e-fable-opus) | Claude Code · `/i2e-fable-opus <task>` |
| [i2e-opus-sonnet](https://github.com/bowang-solutionstream/i2e-team/tree/i2e-opus-sonnet) | Claude Code · `/i2e-opus-sonnet <task>` |

## Read the latest library

Use Git and Python 3.10 or later. Opening the default `i2e-astra-sol` branch in Codex makes `$i2e-astra-sol` available in that checkout.

Before every new I2E run and whenever a later session resumes one, the coordinator fetches the latest merged properties and rules from `main`. Do this before project inspection, planning, dispatch or edits, including read-only runs. Set `run` to the private run directory outside the product, and `skill` to the directory of the active skill containing `scripts/fetch_library.py`.

```sh
intake=$(python3 -B "$skill/scripts/fetch_library.py" "$run") || exit 1
library="$intake/library"
cat "$intake/catalog.json"
```

Continue only when the command succeeds. Record the returned snapshot path, the `revision` in `catalog.json` and the relevant record IDs. Read the matching Markdown in `library/properties/` and `library/rules/`. A failed fetch or invalid catalog blocks the run. Report the failure and retry the fetch before continuing. Earlier receipts remain evidence of earlier work. Keep the same snapshot across rounds of this invocation. On resumption, retain the previous receipt and reconcile newly applicable checks with the plan before continuing.

The fetcher makes one fresh, read-only clone from the public `bowang-solutionstream/i2e-team` repository per invocation. It validates both categories at one commit and writes a receipt in a new private directory. From a checkout of this branch, the standalone command is `python3 -B tools/fetch_library.py "$run"`. In Critical I2E, Sol performs the fetch before the probe and passes selected entries locally to Astra.

Adopted entries apply within their stated scope. Candidates are suggestions. Retired entries remain searchable as history. A project owns its own tests, approved rules and release decisions.

Each Markdown file uses the existing I2E library fields. Its filename matches its `id` (`prop-…` or `rule-…`). Set `kind`, `type`, `status`, comma-separated `tags` and `applies-to`, distinct public-safe `seen-in` observations and the `updated` ISO date. Property records contain **Statement**. Rule records contain **Trigger**, **Check** and **Why it flags**. The templates list the allowed types.

## Reflect after delivering

The coordinating session reflects once the requested deliverables, checks and required review all succeed on the final candidate. If delivery includes a release or other requested action, confirm that outcome first. Failed, stale, partial and read-only analysis runs keep observations private. Reflection is part of handoff. Each workflow keeps its existing verifier and number of rounds.

1. Identify each newly demonstrated property and each observed miss. Test a property against an independent expectation. For a miss, identify the trigger in a change and a check that catches it. Omit unproven or project-confidential findings.
2. Create a private directory for this run's drafts. Copy a [property](templates/property.md) or [rule](templates/rule.md) template into `drafts/properties/<id>.md` or `drafts/rules/<id>.md`. Use `candidate` for new records. For a genuinely new observation of an existing entry, copy its latest record and add a distinct, public-safe `seen-in` reference. An empty draft directory is valid.
3. Review the exact proposed Markdown for public release. Generalize identifiers and examples. Keep proprietary code, customer information, private repository or issue references, evidence paths and raw logs on the machine. The built-in pattern check only catches some unsafe strings. A legacy `I2E_LIBRARY` checkout may supply reviewed drafts. Select entries individually and preserve the original checkout.
4. Run the command for the delivering workflow. The tool checks local acceptance, fetches current `main`, deduplicates sightings, commits each category to its own branch and merges each changed branch to `main`. It sends the changed refs together with an atomic fast-forward push. The repository owner has authorized this specific reflection. Authenticated Git write access to the three library refs is required for changes.

```sh
mkdir -p "$run/drafts/properties" "$run/drafts/rules"
# Codex Critical, using the exact controller and state that verified the delivery
python3 -B "$library/tools/library.py" reflect --workflow i2e-astra-sol \
  --entries "$run/drafts" --i2e "$i2e" --state "$state"
# Codex Direct or Standard, using the verified ledger
python3 -B "$library/tools/library.py" reflect --workflow i2e-astra-sol \
  --entries "$run/drafts" --i2e "$i2e" --db "$db" --run "$run_id"
# Claude Code, using the delivering skill's exact name
python3 -B "$library/tools/library.py" reflect --workflow "$workflow" \
  --entries "$run/drafts" --handoff "$run/handoff.json"
```

### Claude completion evidence

The coordinator records the existing final acceptance and review in a **private** JSON handoff when the final candidate is verified. Include every in-scope deliverable and all required check receipts. Hash their final bytes at acceptance. Use absolute paths and lowercase SHA-256 (for example `shasum -a 256 file`). A delivered deletion uses `null` for its digest. The required reviewer follows the selected workflow. The tool re-reads the files and checks the verdict. The coordinator remains responsible for complete coverage and truthful observations.

```json
{
  "workflow": "i2e-fable-opus",
  "status": "PASS",
  "sources": [{"path": "/local/deliverable", "sha256": "<64 hex characters>"}],
  "checks": [{"name": "end-to-end", "status": "PASS", "path": "/local/e2e-result", "sha256": "<64 hex characters>"}],
  "review": {"verdict": "APPROVE", "path": "/local/final-review", "sha256": "<64 hex characters>"}
}
```

### Read the result

| Result | Meaning |
| --- | --- |
| `MERGED` | The tool confirmed the category and merge commits on the remote. Record the returned `main` SHA and entry IDs in the private handoff. |
| `NO_CHANGES` | The run had no new public-safe findings, or the same observations were already present. No commit is necessary. |
| `BLOCKED` | Delivery evidence is missing or stale, or a draft needs correction. Fix the specific condition before retrying. |
| `PENDING` | The public update could not be confirmed. Keep the drafts, report publication separately from delivery, and retry with the same inputs. Concurrent edits are reconciled against fresh refs. |

## Adoption and correction

A merge makes an observation available to the next run. To adopt a property, verify the oracle and obtain agreement to reuse it at its stated scope. To adopt a rule, require two distinct observed changes, a recognizable diff trigger, a user-approved attempt to disprove it that it survived, and agreement to adopt it. Record the evidence and reasoning. Retire obsolete entries with a reason. Maintainers make those curated changes on the relevant category branch and merge it to `main`. The automatic publisher preserves existing definitions and adoption state.

The original public [label verification catalog](https://github.com/bowang-solutionstream/i2e-team/blob/52d9d48b059c57f434bbd69863f1df4a9b04bfaf/skills/i2e-team/references/label-verification.json) retains the underlying runnable checks. Use the local project verifier and replay failing, passing and held-out examples before enabling a rule in a product.

## Test the publisher locally

```sh
python3 -B -m unittest discover -s tests -v
```

The tests exercise intake, failed refreshes and post-delivery publication against a disposable local Git remote. They can run without GitHub credentials.

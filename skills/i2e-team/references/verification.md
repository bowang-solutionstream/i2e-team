# Verification and learning

New Critical work uses the [four-round Critical workflow](critical-four-rounds.md). The v8 procedures below cover Direct, Standard and replay of runs already recorded under the earlier profile.

Evidence and independent assurance for the staged v8 profile. The [runtime guide](runtime.md) and [records reference](records-v2.md) describe the public calls.

## Select verification tools

At planning, identify the user-visible entry point for each E2E acceptance and the language of the code with a property to check. Prefer the project's existing verified harness when it covers that claim. For the staged defaults, run the selector from the pinned skill. Supply only the dimensions that apply.

```sh
python3 -B skills/i2e-team/scripts/i2e.py select-tools --surface web --language typescript --feature labels.normalize
```

A web journey selects Chrome DevTools MCP. API and CLI journeys use the public API or executable. Mobile and desktop journeys need a compatible simulator, emulator or computer-use driver. The property defaults are fast-check for JS/TS, Hypothesis for Python and proptest for Rust. Use another project-supported tool when the surface or language requires it and record the choice in the plan. Include a feature only when its contract applies.

Save the selection with the acceptance ID, journey, independent oracle and exact invocation. Bind the selection, project verification skill, applicable shared catalog and dependency lock to the existing plan artifact and source harness/dependencies. Map supported named checks through the existing `verification_map`. Check the selected tool's prerequisites on the executing host. A missing tool or a setup error leaves the affected check unverified.

The staged repository's `examples/typescript-labels/.agents/skills/verify/SKILL.md` drives a local TypeScript web fixture. The project verifier reads the selected pair and checks the catalog digest before running it. A fresh checkout supplies the skill and lockfile. An isolated Chrome profile and repo-local dependencies supply the driver. Keep machine paths, browser profiles and raw receipts in the local run directory.

At verification, replay the pinned journey through the running app and inspect its observable result. Replay generated properties with their seed and retain any reduced counterexample and replay path. Apply the case and rule procedure below to demonstrated misses. A local capability trial supplies evidence only for its executed checks. A required browser journey needs a qualified execution path before operational acceptance.

## Project catalogs and rule promotion

Keep reusable checks, sanitized examples and the feature's verifier under version control. Use the shared skill repository for cross-project contracts and the product repository for product-specific behavior. A new machine needs the pinned checkout, the project verifier and its locked dependencies.

Run the pinned skill's `scripts/i2e.py select-tools --surface web --language typescript --feature FEATURE --catalog verification/library.json` from the checkout that owns the catalog. The selection records the checkout-relative path, content digest, entry point, check IDs and rule modes. The bundled label catalog also supports the earlier invocation with `--feature labels.normalize`.

A project catalog uses schema `i2e-verification-catalog/v1`. Its `features` object maps a feature ID to an `entrypoint` and a nonempty list of `checks`. Each check has an `id`, `claim` and independent `oracle`. Its `rules` array can start empty. Each learned rule has a unique `id` within the feature, a `feature`, `case_digest`, `status` and one or more sanitized `examples` with JSON `input` and `expected` values.

The project verifier implements the named checks. Recheck the digest and selected IDs against the plan, drive the actual entry point and record outcomes. An unknown required check holds that acceptance. The [verification role](../prompts/verification.md) reruns the applicable evidence.

When passing checks miss an observed defect, retain the raw case in the private case store. Add the reduced example and its expected outcome to a feature-scoped rule in `observe` mode. Record discrepancies without failing an otherwise passing run. Replay the fault, a working implementation and a held-out example. After review of that scope, change the rule to `enforced` and repin the selection. An enforced mismatch fails the feature check. Commit the reviewed rule and regression together so a later checkout can replay them.

## Portable label pilot

Select feature `labels.normalize` for a task whose public `reader.read(list[str])` operation normalizes whitespace while preserving label text, order, duplicates and the input. Acceptance A1 uses the [checked-in property and rule catalog](label-verification.json) and the [local verifier](../scripts/verify_labels.py). Run it against the selected disposable repository using the checkout's Python 3.

```sh
python3 -IB skills/i2e-team/scripts/verify_labels.py --repo /path/to/label-fixture --feature labels.normalize
```

The command drives the public API in a fresh local process. Review the actual selected IDs, sample counts, first counterexample, source identity and exit. The staged pilot binds a copy of this trusted verifier and catalog as read-only harness inputs before TEST_ONLY. Its named A1 unittest executes the pack at RED, GREEN and verifier rerun. The repo's `scripts/pilot_labels_v8.py --help` describes the full disposable controller run and its host dependencies.

For a UI journey, choose the actual app's entry point. A local computer-use driver can perform the actions and read the resulting state when the selected product exposes that UI.

Grade an example rule against its declared output. Include a qualification control whose output is correct but whose input is mutated. The input-preservation check should flag it and the output rule should pass.

Keep first-failure receipts, raw cases and host configuration in a private run directory. On a demonstrated miss, save the broken check and a reproducible input with the canonical failure-case helper. Add a narrowly scoped, sanitized example with its case digest to the catalog in a separate revision. Replay the candidate rule in observe mode on faulty and working controls, including an example held out from the motivating case. Use `pilot_enforced` only for the evaluated label contract. Wider adoption follows the existing review process. A subsequent session can pull the skill repository and use the portable examples directly.

## Evidence

Behavioral RED must fail on the intended assertion. A setup or fixture failure requires diagnosis. GREEN uses the same test path, selector, whole bytes, Git mode, runner, and argument array. Preserve the full mode-bearing candidate, base, test, runner, harness, dependencies, tool versions, command, streams, and exit. The native proof binds harness and dependency modes through its source record and all instruction modes through the candidate.

`proof` executes the literal argument array through the qualified local macOS read-only executor. The command runs with source writes denied and a private writable scratch. The receipt records the observed wrapper, runner identity, raw streams, exit, and qualification probe.

Behavioral `test_id` uses 1 to 512 printable characters on one line, without leading or trailing whitespace. Python uses the exact `Class.method` identity in a direct unittest script invocation with `-B` and `-v`. Node uses the complete top-level test title and `--test`, with at most one `--test-name-pattern=...` before the test path. Named Node coverage uses the observed non-TTY spec report. Generic diagnostics can retain TAP output. See the [record examples](records-v2.md#proof-review-and-case-requests).

The Node 26.7.0 qualification covers one top-level test with zero suites, skips, cancellations, and todos. A synchronous RED starts with the anonymous or named `TestContext` body frame, followed by contiguous `Test.runInAsyncScope` and `Test.run` frames. A post-await anonymous RED starts with `TestContext.<anonymous>` followed by `async Test.run`. The origin must be in the declared test file at or after its declaration in the selected failure block. A `TestHook` or `Test.runHook` frame makes the report ineligible.

Issuance and replay require a single unambiguous named result from the pinned runner. GREEN and mapped CHECK require a passing result for that test. RED requires the assertion failure and the selected body frame in the declared test file. Setup, import, and lifecycle failures, skips, filter exclusions, zero tests, and wrong or duplicate test identities block behavioral proof. Inspect the reviewed test and assertion alongside the native report. An approved nonbehavior CHECK covers only its own check.

Each acceptance maps to a distinct executed result. A native mapped CHECK uses the exact approved `verification_map` during a zero-write VERIFY start. It refreshes relevant current coverage while the acceptance's own behavioral cycle still requires RED and GREEN. Relevant withdrawal or supersession of acceptance or selected decision support invalidates affected proof. Retain evidence for unrelated checks that stay current.

Own GREEN, replay, and worker production revalidate the original selected plan, required approval, consultation, and relevant decision support at TEST_ONLY, RED, and PRODUCTION. Own GREEN also retains its issuance witnesses through consumption. A supported revision between RED and PRODUCTION can qualify while the original selected witnesses remain live. Withdrawal of selected original support blocks its use even after a replacement is approved.

Own GREEN replay compares the effective revisions for the acceptance's relevant and exact-plan-required decision lineages at issuance and at consumption. A relevant post-GREEN revision, including a later revision that restores the previous choice, requires fresh proof. Newly relevant or reassigned lineages and missing required support also invalidate the proof. Unrelated revisions leave the proof usable.

Aggregate CHECK lists exact distinct `{acceptance, proof}` references for every active member of the required aggregate. Each member is a current mapped CHECK from the same VERIFY start or a current GREEN from the same PRODUCTION start, as applicable. Validate the native subresults and current plan, source, and start on replay.

After a sequential repair, rerun unaffected behavioral acceptance on the actual combined source. Carry requires the prior acceptance's genuine own RED and GREEN, unchanged full test and execution identity, continuous authority, and current proof. A relevant decision revision or a recorded test, instruction, harness, or dependency mode change during carry blocks reuse even after restoration. A mode-only change can make native, mapped, and aggregate proof stale and reopen dependent case and finding checks. Earlier passing receipts remain historical.

Use targeted negative controls for important new behavior. Run destructive or mutation probes on disposable copies. Preserve the accepted candidate. Reuse applicable suite evidence for the same candidate and setup. Refresh affected evidence after source, base, dependency, harness, instruction, or profile changes. Assess semantic dependencies when file names differ.

Reviewers execute the key acceptance and selected failure cases themselves. They inspect assertions, changed code, callers, and relevant dependencies. Distinguish EXECUTED from INSPECTED in the report. Precise source or security evidence can support a finding when execution would be unsafe. State its limits.

## Decisions and review

Non-trivial decisions receive an independent challenge before dependent work. A meaningful RED may challenge its mapped ordinary behavioral claim. Significant architecture or Critical questions require Astra. One plan-review packet can support exact-plan approval and distinct mapped decision verdicts. Direct omits separate plan approval and retains decision challenges.

The independent verifier excludes planners, coordinators, implementers, and other relevant contributors. Baseline code, security, and test auditors are distinct eligible sessions. Each selected required v2 audit stays live and records the current candidate, at least one actually executed approved check with its argv, passing exit and both raw streams, and at least one inspected owned source path. Inspection-only findings may be recorded for resolution. Apply the architecture and final-review exclusions in the [policy reference](policy.md).

Review findings need a stable ID, affected requirement, evidence, consequence, smallest correction, and validation. An empty findings list is valid. High means serious harm to an essential workflow, security, integrity, or reliability. Medium means a concrete defect or maintenance problem with material bounded impact. Low observations record location, reason, and revisit trigger without opening a routine repair loop.

FIXED actionable findings retain current passing proof and a Sol rechecker distinct from contributors and the original finder. One eligible session can recheck several findings. Older actionable findings stay open until valid disposition. NOT_APPLICABLE requires evidence. Material risk acceptance requires the actual human decision tied to the finding and candidate.

## Failure boundary

Save the first failing command's actual output, exit, command, and relevant broken source and harness identity before correction. Preserve recoverable bytes or a durable snapshot in private storage.

Capture a canonical case before repairing an unexpected acceptance or regression failure, a material business-logic or safety defect, a failed repair, or a routine iteration problem repeated after an attempted correction. Preserve expected assertion RED as test evidence. A `failure_classification` of `ROUTINE_SETUP` requires actual isolated import or syntax evidence. If the same stable defect recurs, retain its original output when canonical capture becomes required.

Use the existing canonical helper and schema. Consult cases before planning, each canonical-defect repair, and final acceptance. Carry known digests and applicable regression obligations regardless of search ranking. Missing lookup, incomplete readback, and saturated search remain evidence gaps.

Use `case bind` for an exact inherited case/check pair in reviewed remediation. Bind the current canonical reproduction, repair consultation and applicability decision, exact prior run prefix, case origin, and stable defect. Retain unrelated checks and inherited repair counts. After two failed repairs of a stable defect, obtain Astra diagnosis before a third. Three unresolved substantive cycles of a decision stop dependent work and surface the decision to the owner.

## Final acceptance and learning

Resolve findings, required specialists, and final case regressions before required Astra final review. The final reviewer assesses the current candidate, prior dispositions, remaining uncertainty, and the lawful success path. The selected final Astra approval must remain live. Its withdrawal or supersession holds acceptance until a fresh qualifying final review, even when earlier approvals remain live.

Check current proof, approvals, independence, findings, authority, and reported status. Follow technical readiness with the [engineering brief](teaching.md) and current completion check. Preserve the scope of the actual result.

Record useful maintainability observations even when tests pass. Prefer a local correction or deterministic check before a broad new rule. Compare proposed reusable rules against motivating and held-out cases, including legitimate behavior they might block.

Adopt, narrow, consolidate, retire, or defer a rule through existing review and authority. Preserve history and still-applicable requirements. A pending lesson holds the original task only when it also constitutes a material finding.

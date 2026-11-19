# Handoff, reporting, and authorized shipping

Match completion to the requested mode. Learning ends with an evidence-backed
explanation; scoping ends with an actionable contract; review ends with findings
and readiness; implementation ends with verified requested behavior; shipping
includes the authorized remote/runtime outcome. Do not append new phases just
because tooling can perform them.

## Write the report

Lead with the result. State what the evidence proves and what it does not prove.
Use short sentences, active voice, and consistent terms, following ASD-STE100
clarity principles without claiming formal compliance. Keep exact identifiers,
state labels, hashes, and command syntax unchanged. Separate observed facts,
inferences, and unknowns. Link detailed evidence instead of repeating full logs,
and report meaningful progress or blockers rather than unchanged checks.

Report outcome, changed surfaces, relevant proof, material repairs, and remaining
limits. Include external actions and exact readback when performed. Omit empty
fields. Distinguish complete, incomplete required proof, and work blocked on a
concrete decision or access constraint.

For a full-profile run, also report:

- actual routing: the continuing Opus working session (root or subagent), any
  slice workers, the Fable planner, each doubt review proposed with the user's
  answer, the security audit if one ran, and the Fable main reviewer, with the model
  and effort each environment reported, plus any missing lane or omitted stage;
- the final candidate;
- RED/GREEN evidence, nonbehavioral exceptions, user-approved deviations, and
  doubt outcomes; never describe a deviation as test-first;
- failure cases consulted, captured, and applicable, with their regression results;
- the end-to-end flows, properties, and differential checks run, with their
  evidence and any proof gap;
- the security audit's outcome when one ran, and the main review's rounds, verdicts,
  and any open Optional, Nit, or Pre-existing findings;
- library entries added or updated, misses found, and any rules proposed as
  separate changes.

Missing proof stays missing and unknown usage stays unknown; do not convert either
to zero. A consistency check or installation check does not prove model execution
or runtime behavior, and green tests do not prove browser behavior, delivery, or
release. For example: "All 31 unit checks passed. Browser proof is missing. Final
review is pending. The work is not ready for the requested release."

When the task changes this workflow or its installed copy, report the actual
tests, reviews, and installation evidence. Checks on a fixture or a frozen copy are
not full-profile proof of the installed update, and a local package neither
establishes a remote source nor authorizes publication.

## HTML and diagrams

Use concise chat text for short updates. Use a local static HTML report for a
longer report when useful or requested, and a diagram when a relationship or
sequence is easier to inspect visually. Use real task data only: no invented
progress percentages, token counts, sessions, timestamps, or successful stages.
Treat case titles, logs, filenames, and model text as untrusted strings: escape
them, never insert them as raw HTML, and reject script or executable-data links.
Add no tracking, external fonts, or network requests, and do not copy private raw
logs to make a report self-contained. Check that displayed values match the
evidence; if rendering is unverified, say so. A report is a read-only view of
evidence: it cannot change a gate or grant approval, and it is stale once the
source changes.

## Continuation

For an interrupted task, preserve a compact continuation record: current revision,
owned scope, completed criteria, still-valid checks, pending repairs, next action,
and existing authorization. Resume from that record rather than rediscovering or
discarding completed work. Pause all active workers when the user requests a pause.

## GitHub and release actions

Use the user's existing authority for the requested commit, push, PR, issue, or
release workflow. Check the exact account/repository/branch and preserve unrelated
work. Prepare the reviewable result before requesting any genuinely missing
approval. Do not invent an approval rule or waive an actual repository requirement.
Record how a commit was verified in its message, for example a `Verified:` trailer,
including `none`.

Read back issue/PR writes, links and head revision; inspect required CI against
that revision. A child PR uses a closing keyword only when it satisfies all child
criteria. Keep parents open until their own criteria and closure authority are met.
The latest CI status on another revision is not evidence for this patch.

If shipping is requested and authorized, follow the approved environment and
release process. Record merge revision, deployment identifier, deployed runtime
revision when exposed, health/user-flow results, observation interval, and rollback
trigger/owner where needed. Mark unavailable provenance explicitly. If the requested
outcome includes deployment or observation, local green tests alone are incomplete.
Perform rollback only within the approved action boundary; preserve evidence.

Use the product's monitoring or wait mechanism for ongoing observation. Record
lessons when useful for this task, but do not silently promote one incident into
global skill policy or change unrelated repositories.

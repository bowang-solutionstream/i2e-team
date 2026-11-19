# Opus 5.5 Max / Sonnet 5.5 Max routing

## Runtime and roles

Use runtime-provided model and effort identifiers. This profile requests
`claude-opus-5-5` with `max` effort and `claude-sonnet-5-5` with `max` effort. In
Claude Code a subagent's model and effort come from its definition: the bundled
[`i2e-opus-lead`](../agents/i2e-opus-lead.md) and
[`i2e-sonnet-implementer`](../agents/i2e-sonnet-implementer.md) pin them, and the
package installer registers them as user-level agents. Leave `model` and `effort`
unset in Agent calls so the definitions supply both. Verify the effective model
and effort in `/tasks` or runtime metadata when available. Check for environment
overrides or managed caps if the runtime reports different values.

Confirm both agent types are available before delegating. A missing type means an
incomplete installation: report it, and install the bundled definitions only when
authorized; a new session may be needed to load them. If the runtime cannot run the
requested pairing, explain the limitation; continue useful non-model-dependent
work and obtain a user-selected fallback before representing another profile as
the requested hybrid. A skill does not provide model access, subscriptions, or quota.

If the root is already Opus 5.5 at max effort, it is the decision lead. Otherwise,
create one `i2e-opus-lead` with a focused contract/discovery task and reuse it for
ordinary review by continuing it with SendMessage. The root relays tools and
integrates work without duplicating the lead's planning. Current-agent direct work
remains appropriate for tiny tasks and non-implementation requests; report that
exception honestly.

Opus owns the contract, architecture, cross-module invariants, material scope
changes, and final judgment. Sonnet implements stable, bounded work, writes relevant
tests, and repairs local failures. For an uncertain migration, concurrency defect,
tenant boundary, or other consequential invariant, Opus investigates and can
implement the critical part; delegate only the separable settled portion.

## Delegation packet

Give each worker the objective, exact base/worktree, owned files or module, relevant
pattern, invariants and exclusions, acceptance-to-proof map, the repository's
verification assets and `REVIEW.md` when relevant, the matching library entries and
the absolute path of the library guide, allowed commands and actions, and unresolved
questions. Include direct source pointers so it can inspect necessary dependencies;
an evidence capsule is not a ban on useful investigation. Subagents do not inherit
this skill, so point them by path to the bundled references they need, such as the
review standard for a reviewer. Tell workers they share the codebase and must
preserve others' changes. Do not fork the whole conversation just to populate a task
packet.

For Claude Code's Agent tool, the relevant fields are:

```json
{
  "description": "Implement pagination slice",
  "subagent_type": "i2e-sonnet-implementer",
  "prompt": "The task-specific contract, owned paths, evidence, and verification."
}
```

Start a separate `i2e-sonnet-implementer` for each slice that needs one; implementers
with disjoint write ownership can run in parallel. For a separate decision lead or
fresh critical reviewer, select `i2e-opus-lead` and a fresh bounded context. Follow
the actual tool schema if different. Use subagents rather than starting user-visible
sessions unless the user asks for one. The root owns worker spawning, integration,
and relay. Workers request additional help through the root so overlapping work and
repeated investigation remain visible. Do not spend a slot on duplicate verification
of unchanged inputs.

## Review and repair

Each Sonnet worker returns changed files, decisions, acceptance/proof mapping,
commands and outcomes, unresolved concerns, its reported model, and usage metadata
when available.
Opus reads the actual production diff and important test assertions, including
omitted behavior. For ordinary review, reuse the lead promptly. For consequential
changes, use an independent `i2e-opus-lead` reviewer with the requirements, raw
diff, and evidence; avoid feeding it the author's approval conclusion as its task.

Consolidate material findings into one repair packet per affected slice and return
ordinary fixes to the Sonnet worker that owns it. After two unsuccessful rounds, or
earlier evidence of a misunderstood invariant, Opus diagnoses the cause, corrects
the contract, and takes over or reassigns a smaller settled slice. If the same
required check still fails after a third round, stop that item and bring the
evidence to the user. Do not create an endless relay or use the repair count as a
completion condition. Parallel workers must have disjoint write ownership;
shared-contract changes happen before dependent implementation.

## Cost accounting

Optimize cost per accepted result. Record actual model/effort, input/cached/output
usage, reasoning usage if exposed, elapsed time, repair count, and proof quality.
Include root coordination, workers, reviews, retries, and evaluation in comparisons.
Do not count cached input twice, or add reasoning output twice when the provider
already includes it in output. State missing usage as unavailable. Estimated rate
card credits are not observed account charges or quota savings; date the rate card.
Measure Opus/Sonnet quality and cost on the same tasks before comparing it with
earlier routing profiles.

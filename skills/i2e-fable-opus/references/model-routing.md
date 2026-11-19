# Fable 5.2 Max / Opus 5.5 Max routing

## Lanes and subagents

This profile uses two model/effort lanes only:

- `claude-opus-5-5` / `max`: the continuing working session (intake, exploration,
  research, implementation, tests, end-to-end proof, repairs, evidence, handoff),
  any bounded slice workers, the doubt reviews the user approves, and the security
  audit when a change needs one.
- `claude-fable-5-2` / `max`: the substantive initial plan and test strategy,
  material replanning, and the main code review.

In Claude Code a subagent's model and effort come from its definition. The bundled
definitions pin them, and the package installer registers them as user-level
agents:

| Agent type | Lane | Tools | Use |
| --- | --- | --- | --- |
| [`i2e-opus-implementer`](../agents/i2e-opus-implementer.md) | Opus 5.5 / max | All but Agent | Continuing worker or slice worker |
| [`i2e-fable-planner`](../agents/i2e-fable-planner.md) | Fable 5.2 / max | Read-only | Initial plan, material replan |
| [`i2e-opus-doubt-reviewer`](../agents/i2e-opus-doubt-reviewer.md) | Opus 5.5 / max | Read-only | Approved decision challenge |
| [`i2e-opus-security-auditor`](../agents/i2e-opus-security-auditor.md) | Opus 5.5 / max | Read-only | Triggered security audit |
| [`i2e-fable-final-reviewer`](../agents/i2e-fable-final-reviewer.md) | Fable 5.2 / max | Read-only | Main code review |

Read-only subagents may use only Read, Grep, and Glob; their definitions also deny
Edit, Write, NotebookEdit, Bash, Agent, WebFetch, and WebSearch. The implementer
keeps the session's tools except Agent, so only the coordinator starts subagents.
The Agent tool's per-call `model` and `effort` arguments override a definition, so
pass neither. The `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` and `CLAUDE_CODE_EFFORT_LEVEL`
environment variables also override the pins; when either is set, record it and do
not claim the pinned lanes. Max is not an instruction to invent an API parameter.

Confirm that every agent type is available before a full run, and that no
project-level agent with the same name overrides the installed one. A missing type
means an incomplete installation: report it, and install the bundled definitions
only when authorized; a new session may be needed to load them. If the runtime
cannot run a required lane, explain the limitation and continue useful work that
does not depend on it. A missing lane prevents a full-profile claim; a fallback the
user selects is reported under its actual routing, never as this profile. Record
the actual model, effort, role, and agent ID of every subagent. A role name,
installed definition, or self-report does not prove that execution happened. A
skill does not provide model access, subscriptions, or quota.

## Root and the continuing working session

The root session is the coordinator: it dispatches every subagent, relays results,
asks the user, and keeps the run record. If the root runs `claude-opus-5-5` at max
effort, as its environment or the user states, it is also the continuing working
session; treat an unknown effort as not max. Otherwise, start one
`i2e-opus-implementer` at intake, continue that same subagent with SendMessage for
every ordinary phase, and record its agent ID as the working session. In that case
the root makes no edits to the project repository and produces no checks; it
inspects, relays, records, and writes the library entries. A phase or role name
alone does not need a new worker.

Start bounded slice workers only for a concrete context need, separable parallel
work, or an ownership boundary. Parallel workers need disjoint write ownership, and
shared-contract changes happen before dependent implementation. The working
session stays responsible for integration.

Direct work in the current agent remains appropriate for tiny nonbehavioral tasks
and read-only requests; report that exception and the omitted stages honestly.

## Dispatch packets

Give each subagent the objective, exact base/worktree, owned scope or report-only
ownership, the contract, the plan, existing authority, known failure cases, evidence
pointers, the repository's verification assets, `REVIEW.md`, and matching library
entries when relevant, allowed commands and actions, and its stopping point.
Subagents do not inherit this skill, so give the absolute paths of the bundled
references and guides they need, resolved from this skill's base directory. Tell
writers they share the codebase and must preserve others' changes. Give reviewers
the raw artifact and a neutral question, not the author's conclusion. Do not fork
the whole conversation just to populate a packet.

For Claude Code's Agent tool, the relevant fields are:

```json
{
  "description": "Main code review of the final candidate",
  "subagent_type": "i2e-fable-final-reviewer",
  "prompt": "Contract, plan, candidate, diff and evidence paths, REVIEW.md and library rule copies, guide paths."
}
```

Follow the actual tool schema if different. Use subagents rather than starting
user-visible sessions unless the user asks for one. Subagents ask the root for more
help instead of starting their own, so overlapping work stays visible. Do not spend
a slot on duplicate verification of unchanged inputs.

## Plan

After intake and the pre-plan failure consultation, start a fresh
`i2e-fable-planner` with the real contract, evidence, and matching library entries.
It returns the approach, exact scope, acceptance mapping, required checks, test
strategy, risks, and decisions, and flags the hard-to-reverse decisions that may
deserve a doubt review. Save its exact response in the private task directory. The
planner supplies the plan directly; no second approval lane is required, and actual
user authority still constrains writes and exceptions.

The working session may refine implementation details within that plan. A material
change to scope, acceptance, or design goes back to a fresh Fable planner: keep the
earlier record and evidence, carry every known failure case and its regression
duties, rerun the affected proof, and do not treat the later plan as approval for
earlier writes.

## Doubt reviews need the user's approval

A doubt review is worth its cost only for a decision that is hard to reverse or has
a wide blast radius: a data or persistence format, a migration, a public API or
schema, an authentication, permission, or tenant boundary, a deletion, concurrency
or consistency, or an irreversible external effect. Never start one without asking.

Ask before any doubt review runs, at a natural pause such as right after the plan.
First write each proposal in full in your message:

- the decision's ID and what it decides;
- why a doubt review is needed here: the specific risk and what a wrong decision
  would cost;
- what the reviewer would examine: the files, invariants, and failure modes, and the
  neutral question it would answer;
- the cost: one fresh, read-only Opus 5.5 Max subagent.

Then ask with the AskUserQuestion tool where it is available. Its questions take two
to four short options. For one proposal, offer "Run the review" and "Skip it"; for
several, ask one multi-select question with an option per decision, labeled with
the decision's ID and a few words, and split more than four across questions. An
answer of "Other" or no selection declines.

Run a fresh `i2e-opus-doubt-reviewer` only for an approved decision, before the work
that depends on it. Record each proposal and the user's answer. A declined decision
goes ahead: record the risk, give it to the main reviewer, and name it in the
report. When a new hard-to-reverse decision appears during work, stop before the
work that depends on it and ask the same way. A review is not repeated after
ordinary code changes; propose a new one only when the decision itself changes. In a
run where the user cannot be asked, run no doubt review; treat each proposal as
declined, give it to the main reviewer, and report it as not run.

Routine uncertainty, unsuccessful repairs, and interim review stay with the Opus
working session; there is no automatic escalation to Fable after a failure count. A
material design change still returns to Fable planning. If the same required check
still fails after three repair rounds, stop that item and bring the evidence to the
user. If progress needs a consequential user choice or authority that is absent,
surface that decision while continuing independent authorized work.

## Security audit and main code review

When the diff touches authentication, authorization or permissions, sessions or
tokens, input parsing or deserialization, rendering of untrusted content, query or
command construction, secrets or credentials, file or URL paths, new external
endpoints, webhooks, redirects, or CORS, destructive operations, cryptography,
dependencies or lockfiles, external calls, logging of user data, or the tools and
permissions of an AI agent, start a fresh `i2e-opus-security-auditor` after the
final proof and before the main review. The main reviewer can ask for one when it
sees a trigger that was missed.

For the main code review, start a fresh `i2e-fable-final-reviewer`. Never reuse the
planner or any earlier subagent for its first round, and exclude every writer,
repair author, and doubt reviewer. Supply the contract, plan, current diff, relevant
callers, tests and raw check output, end-to-end and blind-spot evidence, failure
consultations, base-revision copies of `REVIEW.md` and the reliability checklist,
the adopted library rules that match, the doubt-review outcomes and any declined or
unasked review, the security report if one ran, and the absolute paths of
`verification.md` and of the code-review-and-quality and test-driven-development
guides.

Only APPROVE closes the run. After a BLOCK, bring the evidence to the user; a
material redesign returns to a fresh Fable planner, and its result gets a fresh
reviewer. After a REVISE, the working session fixes the findings, reruns the
affected tests and flows and then the full suite, build, and linter once, and
continues the same reviewer with SendMessage: give it the change since its last
round and the new evidence, and it checks each earlier finding, the new change, and
anything the change could affect. Start a fresh reviewer instead after a material
replan, or when the new change is larger than the one first reviewed. Continue the
security auditor the same way when a fix touches the triggered area. Review grants
no external authority.

## Cost accounting

Optimize cost per accepted result. A typical run starts two Fable subagents (the
plan and the main review), plus only the doubt reviews the user approves and a
security audit when a trigger applies. Record actual model/effort,
input/cached/output usage, reasoning usage if exposed, elapsed time, repair count,
and proof quality. Include root coordination, workers, reviews, retries, and
evaluation in comparisons. Do not count cached input twice, or add reasoning output
twice when the provider already includes it in output. State missing usage as
unavailable. Estimated rate-card credits are not observed account charges or quota
savings; date the rate card. Matching an earlier Astra/Sol or Astra/Terra benchmark
does not prove Fable/Opus quality or savings. Runs on Fable 5.1 are not a token
baseline for Fable 5.2: the same effort level can mean a different amount of
thinking on each model. Fable 5.2 also has its own rate limit, separate from Fable
5.1's.

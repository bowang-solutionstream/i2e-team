# Provenance and upstream notices

## Primary upstream credit: Addy Osmani

Credit to Addy Osmani's [agent-skills](https://github.com/addyosmani/agent-skills)
for the foundational engineering skillset behind this workflow's adapted planning,
incremental implementation, testing, source-driven development, and review guidance,
and for the bundled lifecycle guides and specialist reviewer roles. This package
consolidates those practices with the locally authored Issue-to-Edit orchestration
and Fable/Opus routing. It is an independent adaptation, not an official release of
the upstream skillset or a claim of upstream endorsement.

## Current adaptation — 2026-10-26

This Claude Code package was updated on 2026-10-26 from
[i2e-astra-sol](https://github.com/bowang-solutionstream/i2e-astra-sol), source
revision `6c030e3fe0bb0133a793ce70a8d99717aaf6cecc`, profile
`i2e-astra-sol/native-v2`, the Codex package of the same workflow. Fable 5.1 Max
takes Astra Max's role (substantive planning and the independent final review), and
Opus 5.5 Max takes Sol Max's role (the continuing working session, fresh doubt
reviews, and the three specialist audits). Routing uses pinned Claude Code subagent
definitions, and the planner and reviewers have read-only tool lists.

On 2026-11-16, at the owner's request, the two Fable roles moved from
`claude-fable-5-1` to `claude-fable-5-2`, still at `max` effort. Nothing else in
the role contract changed.

The 25 lifecycle guides, their support files, and their manifest are copied
unchanged from that package. They snapshot Addy Osmani's agent-skills revision
`aeac41d4d005999432bb7312f7ff06383a91d59d` (v0.6.13): each guide is the upstream
`SKILL.md` with a two-line header, and `idea-refine` and `spec-driven-development`
also carry that package's small reference adaptations. The manifest records upstream
and bundled hashes. The three specialist subagents adapt that package's role
prompts, which adapt the upstream `agents/code-reviewer.md`,
`agents/security-auditor.md`, and `agents/test-engineer.md` at the same revision.

The workflow, routing, engineering, issue, verification, failure-case, and handoff
guidance was rewritten for Claude Code. The following were not carried over: Codex
interface metadata, the strict JSON record checker and its schema, the offline
failure-case store helper, the suite packaging helper, and the inactive historical
bridge, packet, and Pro-stage material. The run record and failure ledger are kept
by instruction instead. The Codex package is provenance, not an installation or
runtime dependency.

## Verification practices — 2026-11-19

The end-to-end, property, and differential testing guidance, the rules for keeping
checks honest, and the misses-to-rules loop in
[verification loops](references/verification-loops.md) adapt practices that Addy
Osmani describes in
[How the Claude Code team thinks about verification](https://claude.dev/blog/how-the-claude-code-team-thinks-about-verification/)
(Claude blog, 2026-11-16). The guidance is paraphrased and adapted to this
workflow; it implies no endorsement.

## Streamlined workflow and shared library — 2026-11-19

At the owner's request, the Fable final reviewer became the one main code review.
The specialist code-reviewer and test-engineer audits, which adapted Addy Osmani's
`agents/code-reviewer.md` and `agents/test-engineer.md` at revision
`aeac41d4d005999432bb7312f7ff06383a91d59d`, were folded into its checklist. The
security audit now runs only when a change touches a trust boundary, doubt reviews
run only with the user's approval, and the run record is lighter. The skill also
reads and adds to a shared property and rule library that lives outside this
package. These changes are owner-directed, not attributed to the upstream authors.

## Earlier provenance and retained licenses

The previous version of this package was adapted on 2026-09-28 from
[i2e-astra-terra](https://github.com/bowang-solutionstream/i2e-astra-terra), source
revision `1feac0ce92f3d0498ad1dbfcfae0294b9ed081c3`, with Fable 5.1 Max as decision
lead and reviewer and Opus 5.5 Max as implementer. That Codex package was assembled
on 2026-09-08 from the locally authored Issue-to-Edit workflow and hybrid-routing
requirements. Its prior package was `h3ro-dev/issue-to-edit-workflow-skills`.
These repositories are provenance, not installation or runtime dependencies.

The standalone instructions consolidate and rewrite the former multi-skill
workflow. No credentials, client artifacts, or project-specific deployment
configuration are included.

The engineering and issue-writing guidance draws on practices packaged previously
from the following sources. Attribution and license copies are retained with the
installed skill. Upstream source files are not installed as separate skills.

- Addy Osmani, [agent-skills](https://github.com/addyosmani/agent-skills), source
  revision `70b7506ce90e200cb47645ddb3f6b8e84fecc047` for the earlier consolidated
  guidance, and revision `aeac41d4d005999432bb7312f7ff06383a91d59d` for the lifecycle
  snapshot and reviewer roles. Copyright (c) 2025 Addy Osmani.
  [MIT license](notices/ADDY_AGENT_SKILLS_LICENSE); an identical copy is retained
  with the [lifecycle snapshot](references/lifecycle/LICENSE).
- Pattern, Inc., [code-mint](https://github.com/patterninc/code-mint), source
  revision `ee3817c78f85b98701db618337837801cdfc8da6`; former
  `interface-ticket-writer` guidance. Copyright 2025-2026 Pattern, Inc.
  [Apache 2.0 license](notices/CODE_MINT_LICENSE).

The original locally authored wrapper names were `i2e-mode`, `issue-workflow-gate`,
`writeissue-guidance`, and `project-coding-guidance`. The new package does not load
them or the legacy hybrid delivery skill. This notice does not imply endorsement
by the upstream authors or change their license terms.

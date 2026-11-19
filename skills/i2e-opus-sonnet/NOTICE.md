# Provenance and upstream notices

## Primary upstream credit: Addy Osmani

Credit to Addy Osmani's [agent-skills](https://github.com/addyosmani/agent-skills)
for the foundational engineering skillset behind this workflow's adapted planning,
incremental implementation, testing, source-driven development, and review guidance.
This package consolidates those practices with the locally authored Issue-to-Edit
orchestration and Opus/Sonnet routing. It is an independent adaptation, not an
official release of the upstream skillset or a claim of upstream endorsement.

## Verification practices — 2026-11-19

The end-to-end, property, and differential testing guidance, the rules for keeping
checks honest, and the misses-to-rules loop in
[verification loops](references/verification-loops.md) adapt practices that Addy
Osmani describes in
[How the Claude Code team thinks about verification](https://claude.dev/blog/how-the-claude-code-team-thinks-about-verification/)
(Claude blog, 2026-11-16). The guidance is paraphrased and adapted to this
workflow; it implies no endorsement.

## Shared library — 2026-11-19

The skill reads and adds to a shared property and rule library that lives outside
this package, as [the library guide](references/library.md) describes. The library
format and workflow are owner-directed.

## Package provenance and retained licenses

This profile builds on the `i2e-fable-opus` package, adapted on 2026-09-28 from
[i2e-astra-terra](https://github.com/bowang-solutionstream/i2e-astra-terra), source
revision `1feac0ce92f3d0498ad1dbfcfae0294b9ed081c3`, the Codex package of the same
workflow. The Opus 5.5 Max / Sonnet 5.5 Max profile installs its skill and agents
under `i2e-opus-sonnet`. It bundles the workflow instructions, subagent definitions,
and retained notices for standalone installation.

That package was assembled on 2026-09-08 from the locally authored Issue-to-Edit
workflow and hybrid-routing requirements. Its prior package was
`h3ro-dev/issue-to-edit-workflow-skills`. That repository is provenance, not an
installation or runtime dependency.

The standalone instructions consolidate and rewrite the former multi-skill
workflow. Changes include lead/implementer model routing, a shared authority and
acceptance contract, proportional proof, final-state review, and repair escalation.
No credentials, client artifacts, or project-specific deployment configuration are
included.

The engineering and issue-writing guidance draws on practices packaged previously
from the following sources. Attribution and license copies are retained with the
installed skill. Upstream source files are not installed as separate skills.

- Addy Osmani, [agent-skills](https://github.com/addyosmani/agent-skills), source
  revision `70b7506ce90e200cb47645ddb3f6b8e84fecc047`.
  Copyright (c) 2025 Addy Osmani. [MIT license](notices/ADDY_AGENT_SKILLS_LICENSE).
- Pattern, Inc., [code-mint](https://github.com/patterninc/code-mint), source
  revision `ee3817c78f85b98701db618337837801cdfc8da6`; former
  `interface-ticket-writer` guidance. Copyright 2025-2026 Pattern, Inc.
  [Apache 2.0 license](notices/CODE_MINT_LICENSE).

The original locally authored wrapper names were `i2e-mode`, `issue-workflow-gate`,
`writeissue-guidance`, and `project-coding-guidance`. The new package does not load
them or the legacy hybrid delivery skill. This notice does not imply endorsement
by the upstream authors or change their license terms.

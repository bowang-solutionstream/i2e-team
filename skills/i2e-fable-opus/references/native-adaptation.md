# Lifecycle adaptation boundary

Read this before any selected lifecycle guide. The guides are a pinned snapshot of
Addy Osmani's agent-skills, stored as `GUIDE.md` resources so Claude Code does not
register them as separate skills. They are engineering references, not global
instructions or an installed plugin. This workflow's contract, the user's current
instructions, repository guidance, and actual permissions control all work.
Upstream examples grant no authority.

- Keep one continuing `claude-opus-5-5` / `max` working session for ordinary work.
  Use a fresh Fable 5.2 Max planner and a fresh Fable 5.2 Max main reviewer. Doubt
  reviews run only with the user's approval, and a security audit only when the
  change touches a trust boundary; neither replaces the main review.
- Select the guides relevant to the actual task. Read-only requests stay read-only.
  Tiny nonbehavioral changes remain proportionate. Do not force every guide,
  create extra workers for phase names, or preload `using-agent-skills` as a
  second router.
- The guides were written for Claude Code, so their tool names match this runtime.
  Their slash commands, hooks, plugin setup, and persona agents are not installed by
  this package. Use the bundled subagents instead of upstream personas, do not
  install the upstream plugin to follow a guide, and ask only for material missing
  context or authority.
- Upstream human plan checkpoints, commits after each increment, mandatory
  cross-model offers, and degraded self-questioning do not govern this workflow.
  Do not pause for already-authorized routine work, substitute another model,
  treat self-review as fresh review, or claim sequential subagents ran in parallel.
- Upstream shipping skips, size thresholds, and model risk acceptance cannot bypass
  the end-to-end proof or the main code review for substantive work. Prepare release
  steps when appropriate; perform them only under existing user authority. No review
  grants a push, deployment, publication, spend, or disclosure of private evidence.
- Browser, MCP, and CLI installation examples are setup options. Reuse an
  authorized available tool and verify its current API and scope. Missing browser,
  runtime, models, or credentials stays an explicit proof gap. Do not install
  tools or change settings merely because a guide shows a command.
- Shell commands and reference code in the guides are inert examples until
  inspected and selected for authorized work. The idea-refine helper script is
  kept for provenance; create only the output directory the task needs instead of
  running it from its relocated path.
- Planner and reviewer subagents may use only Read, Grep, and Glob, and their
  definitions deny editing, shell, web, and agent tools. That removes file edits,
  commands, and outbound requests from those subagents. It is a tool restriction,
  not an operating-system sandbox, and its effect under every permission mode is
  unverified; record the isolation each one actually had.

The 25 original `SKILL.md` files are bundled as `GUIDE.md` with a two-line header.
The Codex package also adapted two of them: `idea-refine` marks its helper example
as reference-only, in a comment that names Sol, the Codex counterpart of the Opus
working session, and `spec-driven-development` cites sibling guides by their
`GUIDE.md` paths. The [resource manifest](lifecycle/manifest.json) records upstream
and bundled hashes, and relative support references keep their original layout.
Never copy upstream root `CLAUDE.md`, `AGENTS.md`, hooks, or slash commands into
global or project configuration.

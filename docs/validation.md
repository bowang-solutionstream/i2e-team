# Validation evidence

## Published to i2e-team — 2026-11-19

- This branch holds `i2e-fable-opus` with the installer, validator, tests, and
  library tool. Those tools, the library template, and the library guide are
  identical on the `i2e-opus-sonnet` branch, which holds the other Claude Code
  workflow.
- `python3 scripts/validate.py` passes, and the tests pass: 43 run, and the 3 that
  need the `i2e-opus-sonnet` skill are skipped. Seventeen deliberately introduced
  defects in the tools were each caught by the tests on this branch.
- The skill is the version validated below, except that its library guide now names
  this repository as the source of `scripts/library.py`.

## Streamlined workflow and shared library — 2026-11-19

- At the owner's request, `i2e-fable-opus` was streamlined. The Fable final reviewer
  is the one main code review, with the code-reviewer and test-engineer checklists
  folded in. The security audit runs only when a change touches a trust boundary,
  doubt reviews run only with the user's approval, later review rounds look at the
  change since the last round, and the run record is lighter. Its subagents went
  from seven to five.
- The skill reads and adds to a shared property and rule library outside this
  repository; `scripts/library.py` and `library-template/` create and check it.
- An independent review of the restructure found no blocking issue and twelve
  should-fix issues, plus small wording issues. Among them: the doubt-review
  question did not fit the question tool's two-to-four options, no role clearly
  owned library writes, a push could be approved without the user seeing what would
  go out, repeated `seen-in` references could satisfy the two-change adoption rule,
  a `#` in a reference was cut off, and a failure partway through installing the two
  skills could leave them at different versions. All were fixed before the results
  below; the fixes were not reviewed again.
- With both skills in one tree, `python3 scripts/validate.py` validated both, and
  all 43 tests then in the suite passed. Seventeen deliberately introduced defects
  in the validator, installer, and library tool were each caught, among them a
  missing rollback across skills, empty backup folders left after a rollback,
  repeated `seen-in` references counted as separate changes, a `#` cut from a
  reference, no fallback for Git before 2.28, and no cleanup after a failed `init`.
- `scripts/library.py init` and `check` were run on disposable folders, and `check`
  passes on the library template and on a newly created library.
- The skill was reinstalled at user level with `--update`, which kept the previous
  copy in a timestamped backup; `--check` reports it as current. The Claude Code
  session that made the change dropped the two removed subagents from its agent list
  after the reinstall.
- These are instruction and tooling changes. No subagent from this version has been
  started yet, and no live workflow run has used it.

## Earlier evidence

### Verification practices — 2026-11-19

- Added `references/verification-loops.md` (end-to-end, property, and differential
  proof; rules that keep checks honest; turning misses into rules) and
  `templates/verify-skill.md`, with pointers in the workflow, references, agents,
  and run record. The guidance adapts Addy Osmani's article on how the Claude Code
  team verifies changes.
- The blind-spot checks that had been edited into the installed copy on 2026-11-18
  were merged into the source, so reinstalling keeps them.
- `python3 scripts/validate.py` passes, and all 33 tests pass. An independent review
  found one blocking defect (the merge above) and seven should-fix issues, all fixed
  before these results; it judged the end-to-end and property guidance faithful to
  the article. The fixes were not reviewed again.
- These are instruction changes. No live workflow run has exercised them yet.

### Fable 5.2 switch — 2026-11-16

- The planner and final reviewer now pin `claude-fable-5-2` at `max` effort.
  `python3 scripts/validate.py` passes, and all 33 tests pass. The model-pin test
  also rejects the previous `claude-fable-5-1` pin, and a copy whose validator still
  pinned 5.1 failed the suite.
- `python3 scripts/install.py --update` replaced the installed skill and agents,
  kept the previous copy in a timestamped backup, and passed `--check`.
- Token use was not measured. Anthropic documents the same tokenizer as Fable 5.1
  and a lower price per token ($8 / $40 against $10 / $50 per million input / output
  tokens), but publishes no comparison of the two models at `max` effort. No token
  saving is claimed for this switch.
- In the Claude Code session that made the change, two one-line checks of
  `i2e-fable-planner` both reported `claude-fable-5-1`: that session still held the
  agent definitions it had loaded before the reinstall. The effort it reported
  changed between the two checks, so self-reported effort is not reliable evidence.
  A check in a new session has not been run yet.
- Each check used about 4.5k tokens. The previous version's Fable agent, which had
  every tool, used about 53k for a similar trivial prompt. The read-only tool list is
  the likely main reason, but the two runs also differ in Claude Code version.
- No live workflow run has used Fable 5.2 yet.

### Package validation — 2026-10-27 (i2e-astra-sol workflow update)

- `python3 scripts/validate.py`: the bundle passes structure, metadata, the exact
  set of seven subagents and their frontmatter fields, their pinned model and
  effort, the read-only tool lists and deny lists, the lifecycle snapshot against
  its manifest (25 guides, 40 resources, matching SHA-256, no unlisted files), and
  local link checks. The skill's links remain inside its own bundle.
- `python3 -m unittest discover -s tests -v`: 33 tests pass. They keep the previous
  install, update, backup, rollback, symlink, and read-only check coverage, and add
  tests for report-only tool lists, required deny lists, access-widening
  frontmatter fields, a stale agent definition, modified or unlisted lifecycle
  files, unresolved support references, and a strict, complete lifecycle manifest.
- Eleven deliberately introduced validator defects were each caught by the suite:
  removing the report-only tool check, the deny-list check, the exact-field check,
  the unexpected-agent check, the lifecycle hash check, the unlisted-file check,
  the support-reference check, duplicate-key rejection, the upstream pin, the
  25-guide coverage check, and the scaffold exemption for the pinned guides. The
  coverage defect was missed at first; a test for a guide removed from both the
  manifest and the tree was added, and the defect was then caught.
- The agent frontmatter was checked against the current Claude Code subagent
  documentation: `effort: max`, `tools`, and `disallowedTools` are documented
  fields, and user-level agents are discovered in subfolders. An independent
  review compared the package with i2e-astra-sol, found no blocking defect, and
  raised fidelity, consistency, and validator gaps that were fixed before these
  results. That reviewer reported checking the definitions against the agent schema
  of the installed Claude Code 2.1.311; this was not repeated separately.
- A trial installation into a disposable config directory installed the skill and
  the seven agent definitions and passed `--check`. Installing the previous version
  (`c95736c`) and then running `--update` replaced both bundles and kept the old
  `i2e-fable-lead` definition in the timestamped backup.
- The copied lifecycle snapshot matches every hash in its manifest, and its MIT
  license is byte-identical to `notices/ADDY_AGENT_SKILLS_LICENSE`.
- Anthropic skill-creator `quick_validate.py` was not available on this machine and
  was not run for this version.
- CI configuration is supplied as an optional template, not an active workflow;
  local validation results are not presented as GitHub CI results.

### Not yet verified for this version

- The new subagent definitions have not been loaded in a Claude Code session. Agent
  discovery, the runtime effect of the `tools` lists, and the model and effort each
  subagent reports are unverified.
- No live workflow run has used this version. There is no evidence yet of a Fable
  plan, Opus test-first work, doubt reviews, the three specialist audits, or a
  Fable final review on a real task.

### Previous version — 2026-09-28

These results describe the earlier Fable-lead / Opus-implementer version.

- `python3 scripts/validate.py` passed, and 26 unit tests passed, including install,
  exact backup preservation of both bundles, two-bundle rollback, source/target
  overlap rejection, symlink rejection, unrelated skill and agent preservation,
  model/effort pin enforcement, and read-only check/dry-run. Three deliberately
  introduced defects were each caught by the corresponding test. Anthropic
  skill-creator `quick_validate.py` passed.
- A user-level installation reported `install` for the skill and agent bundles,
  then `OK` for both under `--check`. A later `--update` preserved the first
  installation in a timestamped backup, replaced both bundles, and passed `--check`.
- A Claude Code desktop session that was already running listed the new skill
  immediately after installation. The subagent types were not yet available in that
  turn ("Agent type ... not found") and became available at the session's next turn.
- In that session, one `i2e-fable-lead` and two `i2e-opus-implementer` subagents
  were started concurrently without a model override. Asked what their environment
  states, the lead reported `claude-fable-5-1` with max effort and both implementers
  reported `claude-opus-5-5` with max effort. Each used about 53k tokens for a
  trivial prompt, nearly all of it fixed startup context.

### Behavior and limits

Structural checks do not prove that models will make correct decisions. The
Astra/Sol or Astra/Terra smoke tests and policy checks recorded for the Codex
packages are not evidence for this package. No comparison against them,
account-charge measurement, or cost-saving claim is established by this validation.

Model and effort evidence is what each subagent's runtime environment states, not
billing or provider records.

The generic workflow retains project-specific requirements. This package does not
provide browser access, credentials, GitHub permissions, model availability, or
production environment access. Live shipping and high-risk migration behavior
require evidence in the actual target project.

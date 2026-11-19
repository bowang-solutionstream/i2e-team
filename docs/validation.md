# Validation evidence

## Published to i2e-team — 2026-11-19

- This branch holds `i2e-opus-sonnet` with the installer, validator, tests, and
  library tool. Those tools, the library template, and the library guide are
  identical on the `i2e-fable-opus` branch, which holds the other Claude Code
  workflow.
- `python3 scripts/validate.py` passes, and the tests pass: 6 run and 40 are
  skipped. The library tool tests and this skill's validation, installation, update,
  rollback, and pin tests run here; the full installer and validator tests need the
  pinned guides on the `i2e-fable-opus` branch and pass there.
- Of seventeen deliberately introduced defects in the tools, the tests on this
  branch caught thirteen. The other four involve two skills at once or the pinned
  guides, and the tests on the `i2e-fable-opus` branch catch them.

## Shared library — 2026-11-19

- The skill reads and adds to a shared property and rule library outside this
  repository; `scripts/library.py` and `library-template/` create and check it. Its
  library guide is identical to the one in `i2e-fable-opus`.
- An independent review of the two skills and their shared tools found no blocking
  issue. For this skill, the fixes added the adopted library rules to the review
  copies in `verification.md` and `verification-loops.md`, and the matching library
  entries and the guide's path to the packet each subagent receives. The fixes were
  not reviewed again.
- The skill was reinstalled at user level with `--update`, which kept the previous
  copy in a timestamped backup; `--check` reports it as current.
- These are instruction and tooling changes. No live workflow run has used this
  version yet.

## Earlier evidence

### i2e-opus-sonnet verification practices — 2026-11-19

- Added `skills/i2e-opus-sonnet/references/verification-loops.md` (end-to-end,
  property, and differential proof; rules that keep checks honest; turning misses
  into rules) and `templates/verify-skill.md`, with pointers in the skill, its
  references, both agents, and the run record. The guidance adapts Addy Osmani's
  article on how the Claude Code team verifies changes.
- `python3 scripts/validate.py --skill i2e-opus-sonnet` passes, and all 27 tests
  pass. An independent review judged the end-to-end and property guidance faithful
  to the article and raised consistency issues, which were fixed before these
  results; the fixes were not reviewed again.
- These are instruction changes. No live workflow run has exercised them yet.

### Package validation — 2026-09-28

- `python3 scripts/validate.py`: the bundle passes structure, metadata, pinned
  subagent model/effort, and local link checks. The skill's links remain inside its
  own bundle.
- `python3 -m unittest discover -s tests -v`: 26 tests pass, including install,
  exact backup preservation of both bundles, two-bundle rollback, source/target
  overlap rejection, symlink rejection (including symlinked `skills/` and `agents/`
  directories), unrelated skill and agent preservation, model/effort pin
  enforcement, and read-only check/dry-run.
- Three deliberately introduced defects were each caught by the corresponding test:
  a rollback that does not restore backups, a validator that ignores the model/effort
  pin, and a missing symlink check on the `skills/` and `agents/` directories.
- Anthropic skill-creator `quick_validate.py`: the skill passes.
- The frontmatter of the skill and both subagent definitions parses as YAML with
  the expected name, model, and effort values.
- Before porting, the source package's 27 tests passed on the same machine.
- CI configuration is supplied as an optional template, not an active workflow;
  local validation results are not presented as GitHub CI results.

### Installation and discovery — 2026-09-28

- A user-level installation reported `install` for the skill and agent bundles,
  then `OK` for both under `--check`. A later `--update` with the
  multiple-implementer wording preserved the first installation in a timestamped
  backup, replaced both bundles, and passed `--check`.
- A Claude Code desktop session that was already running listed the new skill
  immediately after installation. The subagent types were not yet available in that
  turn ("Agent type ... not found") and became available at the session's next turn.
- In that session, one `i2e-fable-lead` and two `i2e-opus-implementer` subagents
  were started concurrently without a model override. Asked what their environment
  states, the lead reported `claude-fable-5-1` with max effort and both implementers
  reported `claude-opus-5-5` with max effort. Each used about 53k tokens for a
  trivial prompt, nearly all of it fixed startup context.
- A headless CLI check did not run because the CLI's sign-in had expired (HTTP 401);
  the in-session check above replaced it.

### Behavior and limits

Structural checks do not prove that models will make correct decisions. No live
workflow smoke test has been run with this package, so there is no evidence yet of
a completed Fable-led, Opus-implemented run, parallel implementers integrating
separate slices, the two-failed-round takeover path, or live shipping. The
Astra/Terra smoke test and policy checks recorded for the Codex package are not
evidence for this package. No comparison against Astra/Terra, account-charge
measurement, or cost-saving claim is established by this validation.

Model and effort evidence is what each subagent's runtime environment states, not
billing or provider records.

The generic workflow retains project-specific requirements. This package does not
provide browser access, credentials, GitHub permissions, model availability, or
production environment access. Live shipping and high-risk migration behavior
require evidence in the actual target project.

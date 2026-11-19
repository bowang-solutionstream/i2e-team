# Verification loops

Adapted from Addy Osmani's "How the Claude Code team thinks about verification"
(Claude blog, 2026-11-16); see [notices](../NOTICE.md). Use it with
[verification](verification.md): this page says which proof to build and how to
keep the checks honest. Repository instructions and actual authority still apply.

## Find the repository's verification assets

At intake, look for what the repository already uses to verify itself: a project
verification skill (often `.claude/skills/verify/`, close to the code it covers), a
feature map, `REVIEW.md`, a reliability checklist, hooks, and the commands for its
tests, build, and linter. Read rules and checks from the base revision. Record what
exists and what is missing in the run record.

## Run the real system end to end

For user-facing or integration behavior, give the agent doing the work hands and
eyes on the running system, not only unit tests: boot it, drive the real flow, and
inspect the result. Use the repository's verification skill when it exists; look for
`.claude/skills/verify/` and `.claude/skills/run-*` near the changed code. Otherwise
use a bundled Claude Code skill such as `run` or `verify` where the installed
version has one, or the tools this session actually has:

- web: a browser tool or the Chrome DevTools Protocol (CDP);
- mobile: a simulator, or an iOS or Android MCP;
- desktop: computer use;
- backend: the service running locally, driven by an API harness or real requests.

Check each flow against the feature map's expected results, or against the
acceptance criteria when there is no map. Save the step trace, a screenshot or
response capture at the final or failing step, and the name of the step that failed
as files with the run's evidence, so reviewers can open them. A scripted flow, kept
as a test file, that fails before the fix at its intended assertion rather than at
setup can be the failing proof for a user-facing fix; a flow driven by hand is
evidence, not that proof. Run every flow on the final candidate before the final
review. Use test accounts and fixtures, never production data or credentials. A
missing tool, runtime, or account is a recorded proof gap, not a pass.

If the repository has no verification skill and the work keeps touching user-facing
behavior, adding one is a repository change: write it only when the contract
includes it, starting from [the template](../templates/verify-skill.md); otherwise
propose it as a follow-up. If a bundled skill offers to save a recipe under
`.claude/skills/`, keep that file out of the change unless the contract includes it.
Keep the skill fast and reliable, because it is the smoke-test harness every later
change depends on.

## Property tests: statements that should never fail

Where a statement should hold for every input, write the statement first, then let
a property-testing library generate thousands of inputs that try to break it:
fast-check for JavaScript and TypeScript, Hypothesis for Python, proptest for Rust,
or the stack's equivalent. Good candidates:

- round trip: decoding what was encoded, or parsing what was printed, returns the
  input;
- invariant: a value always obeys its rule, such as a balance that never goes
  negative;
- idempotency: running a migration, normalization, or retry twice has the effect of
  once;
- equivalence: optimized code returns what a simple, correct version returns.

Use a library the repository already has; adding one is a dependency change that
needs the contract's authority. Record the seed and the number of runs. A property
that fails before the fix with a counterexample is a valid failing test. Add the
minimal failing input that the library reports as an ordinary example test, and
confirm that it fails before the fix too. After the fix, rerun the property with the
recorded seed and the example test, both unchanged. Property tests add edge cases
the author did not choose; they complement example tests and do not replace
end-to-end proof.

## Differential tests: the old system is the oracle

When a rewrite or migration must keep behavior, run the old and new systems on the
same inputs, generated or sampled within authority, and compare the outputs.
Normalize irrelevant differences such as whitespace, and list the approved
differences in the contract. Every other difference is a defect or a breaking
change.

## Keep checks honest

- A change must not weaken the checks that judge it. Adding tests is normal work.
  Without the contract's authority, do not delete, skip, loosen, or rewrite existing
  tests or assertions, or edit `REVIEW.md`, lint or CI configuration, or the
  verification skill; when the contract allows such an edit, reviewers judge it
  against the base version.
- Run the cheap checks first: before the final review, a commit, or a pull request,
  the repository's tests, build, and linter pass on the candidate, apart from
  failures recorded as pre-existing with a baseline. A hook or `/goal` that the user
  set up can enforce this; this skill installs neither.
- Do not skip a flaky test, add sleeps, or rerun it until it passes. Find the root
  cause. If you cannot find it, removing the test needs the contract's authority and
  a written reason.
- The Opus lead still takes over after two unsuccessful repair rounds. If the same
  required check still fails after a third round, stop that item and bring the
  evidence to the user; continue independent authorized work.
- Build each review round on the last: give it the earlier round's findings and the
  failures recorded in the run record, not the author's conclusions. Give reviewers
  base-revision copies of every `REVIEW.md` that applies, with the files it
  includes, of the reliability checklist, and of the adopted library rules; each
  reviewer chooses the items whose triggers match the diff. A review of an outdated
  candidate proves nothing.
- The source article favors tuning one primary reviewer through `REVIEW.md` over
  adding reviewers. Here the Opus lead is that primary reviewer; keep the separate
  fresh Opus reviewer for consequential or hard-to-reverse changes, as the review
  standard says, put repository-specific guidance into `REVIEW.md`, and have any
  check that brings in a person say why.

## Turn misses into rules

A miss is a defect that the work's own checks did not catch: one found by a
reviewer, a later check, a revert, an incident, or the user. A flaky test is a miss
in the checks themselves. Record each miss in the
[run record](../templates/run-record.md) and add it to the [library](library.md) as
a candidate.

At handoff, look for patterns across changes, not only within this task. Use the
evidence that is actually available: the shared [library](library.md), earlier run
records, reverts in `git log`, and review comments on earlier pull requests, read
with `gh` when that is authorized. A pattern becomes a candidate rule only when it
has appeared in at least two separate changes and can be recognized from a diff;
without that evidence, record the miss and propose no rule. A known incident with a
linked change can also be replayed, with the user's approval: give three fresh
`i2e-opus-lead` reviewers, told to report only, that change's diff. If at least two
find the bug, review can already catch it; if they miss it on a small diff, the gap
is a candidate `REVIEW.md` rule.

Write a candidate as a trigger that a diff shows, the check to run, why it flags,
and the cases behind it. With the user's approval, after telling them which rule,
why it needs testing, and what the reviewers would examine, ask three fresh
`i2e-opus-lead` subagents to try to disprove it, each told to report only; their
tools are not restricted, so that limit is by instruction. Test it against the
changes behind it and a few recent changes that stayed clean: it should flag the
first and not the second. Keep only rules that survive.

Adopt each surviving rule in the library, and propose it as its own reviewable
change, never inside the change it would judge: a `REVIEW.md` entry, a `CLAUDE.md`
line, a reliability-checklist item, a test, or a hook. The user approves it. Start a
new blocking gate in observe mode: log what it would block and review false
positives before it enforces. Rules and checks only grow unless pruned, so remove
the ones that no longer earn their place when you add one.

When a commit is authorized, record how the change was verified in its message, for
example a `Verified:` trailer naming the verification skill, end-to-end flows,
property and unit checks, or `none`.

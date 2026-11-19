# Engineering guidance by surface

Rewritten and consolidated for this standalone package; see [provenance](../NOTICE.md).

Use the relevant entries while implementing. These are complete workflow defaults;
the [lifecycle guides](full-suite.md) add depth for a surface that needs it, and
other specialist skills are optional when available and useful, not package
dependencies. Project-specific contracts, commands, and genuine operational
restrictions prevail.

**Repository and source.** Inspect applicable ancestor and scoped guidance plus the
worktree before edits. Use focused searches and existing conventions. For unfamiliar
APIs or dependencies, verify the needed behavior against current primary
documentation. Separate an observed fact from an assumption. Preserve unrelated
changes, secrets, and client evidence outside the patch.

**Specification and planning.** Define the intended behavior before choosing an
abstraction. Prefer existing code. Split dependent work into coherent outcomes with
clear interfaces and one integration owner. Investigate the riskiest unresolved
assumption early. Use an ADR only for a lasting architectural choice that needs it.
Obtain the Fable planner's substantive initial plan and test strategy before
implementation. The Opus working session owns the working phases and may refine
details within the plan; only material scope, acceptance, or design changes return
to Fable planning. No separate plan approver or routine human plan pause is
required. Preserve user scope and action limits.

**Implementation and simplification.** For each behavioral slice, establish RED,
implement, reach GREEN on the unchanged test, then run the required checks. Size
slices by coherence and risk rather than file count, and respect task dependencies.
Do not introduce flags, wrappers, new dependencies, or layers without a current
need. Remove obsolete code caused by an authorized refactor when references prove it
is within scope; distinguish that from deleting unrelated or uncertain assets.
Commit only within the authorized handoff, not automatically after every slice.

**Bugs and testing.** Reproduce the failure and identify its cause before a patch.
For testable behavior, run the test before the production change and confirm that
the intended assertion fails, not a syntax, setup, or infrastructure error. Preserve
the output and before-state. Run the same test after implementation; a changed test
identity or content requires a new RED. Assert outcomes and meaningful boundaries,
not a copy of the implementation. Use fakes or fixtures for external effects and
shared/table-driven cases when they remain clear. Document justified nonbehavioral
exceptions or explicitly user-approved behavioral deviations; neither is a
fabricated passing test. Preserve existing user code if test-first evidence is
missing. Do not erase work or backdate evidence to claim test-first. Where a
statement must hold for every input, add a property test and keep any minimal
failing input as a regression test; for a behavior-preserving rewrite, compare the
output against the old system ([verification loops](verification-loops.md)).

**Doubt during work.** For a decision that is hard to reverse, propose a doubt
review to the user, saying what the decision is, why a review is needed, and what
the reviewer would examine; run it only when the user approves
([model routing](model-routing.md)). Cover boundary, invariant, security,
concurrency, and hard-to-reverse risks, not merely the happy path. A meaningful RED
test can challenge the specific behavioral claim it covers. Resolve findings against
source evidence. Material redesign returns to Fable planning; ordinary doubt and
repairs stay with Opus.

**API, schema, migration.** Identify callers and compatibility obligations. Use
explicit types and validate boundary inputs. Coordinate changes across contracts,
implementation, fixtures, and docs. For persisted state, examine versioning, retry,
idempotency, interrupted execution, rollback/restore, and data preservation as
applicable. Follow the project's migration policy; do not require down-migrations
when the actual system uses forward fixes or restore procedures.

**UI and browser.** Treat approved design and typed data as the contract. Preserve
loading, empty, error, keyboard, and responsive behavior where relevant. For a
visual defect, capture a measurable baseline and recheck the same dimensions after
the smallest fix. Exercise the actual user interaction end to end, with the
repository's verification skill when it has one; screenshots support rather than
replace runtime evidence. Use the available browser tools and test accounts; do not
invent rendered values or claim authenticated proof from static tests.

**Access and providers.** Check authorization at the actual resource/tenant boundary
and test relevant negative paths. Keep credentials out of prompts, logs, and Git.
For providers, identify the approved account/environment, spend/side-effect limits,
timeouts, retry behavior, and cleanup requirements. Use approved fixtures when live
access is unnecessary or unavailable. Project collection rules still apply.

**Performance and observability.** Measure the observed bottleneck before changing
architecture. Check relevant query counts, memory, latency, bundle/runtime costs,
or concurrency. Add useful signals for new critical paths without logging sensitive
data. Instrument enough to detect the actual failure mode, not every function.

**CI and release.** Use repository-native checks and record revision-specific
results. Before the main code review, a commit, or a pull request, run the tests,
build, and linter once on the final candidate. A successful build is not evidence of
deployment. Verify authorized release steps against the actual environment and
observe the deployed revision, health, and rollback conditions using the
[handoff reference](handoff.md).

**Main code review.** Before the Fable main review, finish the final proof on the
final candidate: the full suite, build, and linter, the end-to-end flows, the
blind-spot checks, and the regression checks. Add a security audit when the change
touches a trust boundary. Capture a finding that names a source defect like a failed
check before its repair, and keep test-first and every failed-check protection.
Later review rounds look at the change since the last round.

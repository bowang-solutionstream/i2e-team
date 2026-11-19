# Worker handoff, delivery, and cleanup

The staged v8 source includes a synthetic macOS worker adapter and a synchronous GitHub merge adapter tested with a local fake provider. Operational model transport and live GitHub target qualification remain open.

## Worker output

Use a named commit as the source handoff. Record repository, task, plan, current attempt, parent/base, commit, test and harness identity, and required proof.

The commit pins source bytes and regular file modes. Worker preparation compares the phase candidate with the exact admitted predecessor's Git tree and materialized worktree. Establish authority, current generation, and isolation independently. Use the local `macos-sandbox-full-clone-v1` mode with an independent clone, verified Git metadata and toolchain, and per-attempt grants for its named test or production paths and private scratch. `prepare`, `qualify`, and `run` record separate results. Unsupported hosts, source states, or operational model transport HOLD.

Read current attempt status before acting. `PREPARED` and `QUALIFIED` describe prerequisites. `POSSIBLE_WRITER` and `DISPATCHED` record launch history. `SUBMITTED`, `ADMISSION_RECORDED`, `REVOKED`, and `CLEANED` describe durable events. Read the operation outcome as well. A revoked generation remains retained while it may contain a writer or recoverable evidence.

On `submit`, bind the exact commit and completed dispatch. `admit` serves the named source objects in a deny-default source sandbox. Native fetch runs in a separate quarantine sandbox using a fixed relay and selected anonymous pipe endpoints. Retain both native receipts, protocol limits, and interrupted or partial results. Verify literal objects, ancestry, tree, file bytes and modes, and the actual write delta against the approved paths before opening integration intent.

Admission requires current plan, phase, actor, generation, revocation state, and ledger sequence. The intent binds the exact reserved admission ref. It records the physical before and intended-after state of integration source files and modes, refs, affected Git object files, and the existence and modes of their parent directories. Existing identical objects retain their physical identity and mode. New objects use the verified staged bytes and modes. The qualified integration Git-directory guard stays held through the native ref writer and the readback of that same projection. The task base and integration HEAD stay pinned. Later generations start from the accepted named commit. Check the actual combined candidate after admission.

After an interrupted integration write, repeat the exact `admit` request with its original expected sequence. The controller verifies the original binding and retained storage, stage, and toolchain. It reads current effects under the integration guard and ledger writer transaction. A busy guard, identity drift, or changed projection holds readback.

After revocation or phase retirement, a pending intent may record its first readback. A saved `PARTIAL` or `UNKNOWN` with a matching verified projection returns its existing `HOLD` and outcome without a new result event. These reads grant zero launch, fetch, import, ref, file, or cleanup effects. `INTENDED` and `NO_EFFECT` are resolved outcomes. Their retries retain the live-attempt requirement and refuse a retired attempt.

- `INTENDED` requires exact equality with the full intended effect.
- `NO_EFFECT` requires exact equality with the full before state.
- `PARTIAL` holds an observed incomplete effect, including object-only import, a torn pack/index import, a ref without its files, or partial file application.
- `UNKNOWN` holds unreadable or unrecognized effects.

An unresolved intent holds dependent work. Cancellation or parent exit leaves writer quiescence unproven.

The separate read-only proof executor grants writes only in its private scratch. See [verification](verification.md) for proof requirements.

## GitHub route

Each project identifies its code repository, target branch, permitted actions, and required checks. Use one PR per accepted batch. Ticket-linked commits preserve source traces; each intermediate commit does not require a full audit.

Map original worker commits to the integrated candidate. Bind review and checks to the final head plus the applicable base, harness, configuration, and dependencies. The head and accepted predecessor comparisons use Git bytes and modes. A change to a candidate's Git mode makes prior acceptance stale.

Before relying on GitHub, qualify the actual `github.com` target, actor, and producer. The adapter supports the traditional protection profile with strict up-to-date checks, an exact GitHub App-pinned check, current-head reviews, stale-review dismissal, last-push approval, enforced administrator rules, and empty review bypass allowances. It requires the recorded non-administrator write actor and trusted rule administration. Additional rules or inherited rulesets hold this route.

`delivery inspect` validates current local acceptance, the Git target and merge inputs, and provider state. A currently accepted, explicitly delegated subset may deliver while its original parent stays open. The required App check summary binds exact head, base, target, plan, mode-bearing candidate, read-only source, current proofs and reviews, and the exact membership event, members, and continuations.

The durable intent records the same local binding. The controller compares it at preparation and guarded dispatch. After the last provider GET, it rechecks local acceptance and authority in the guarded writer transaction immediately before PUT. A refusal here records `NO_EFFECT` with `put_started: false`.

`delivery prepare` records intent. `delivery execute` records dispatch and issues the synchronous REST merge through `gh api --hostname github.com` with `sha` set to the reviewed PR head and `merge_method=merge`. The request's SHA condition binds the head. The selected server controls enforce target freshness and stale-review protection. Read back the resulting merge with the exact ordered `[base, head]` parents. See the [REST merge contract](https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request) and [branch protection rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).

On a new head or target, refresh affected checks and review based on semantic dependency impact. A conflict always needs review of the resolution. A clean merge with disjoint files can still invalidate acceptance. Never use file overlap as the sole freshness test.

The required check producer validates actual execution and review receipts, including independence. Omitted acceptance blocks a passing producer report. The staged package includes the consumer and its local fake-provider checks. Live producer deployment and target qualification require separate evidence.

The adapter validates exact `merge_github` authority at the effect boundary. The supported relation is a merge commit. Squash, rebase, merge queues, stacked PR orchestration, and deployment require separate adapters or qualification.

## Timeouts and other targets

Use `delivery reconcile` to read the durable dispatch and actual result without a second PUT.

The controller derives `DELIVERED` from a durable `INTENDED` result tied to the exact dispatch and intent, with the intent's membership, plan, and candidate still matching current local acceptance. A membership change leaves the original intent available for readback and requires its own current acceptance.

- `INTENDED` records exact result and parent readback.
- `NO_EFFECT` requires refusal before PUT or terminal rejection plus unchanged target readback. A new attempt needs current authority and fresh preconditions.
- `UNINTENDED` records the observed different result and holds for authorized remediation.
- `UNKNOWN` holds unresolved effects. A lost response with an open PR can still be unresolved. Preserve raw receipts and reconcile again only with current authority.

A PR's “merged” state alone does not prove that the intended candidate was delivered.

Deployment adapters are deferred until an actual target exists. A GitHub merge does not imply deployment or customer acceptance. Any future adapter must enforce the relevant immutable artifact and mutable-target preconditions.

## Cleanup

Use explicit cleanup authority and durable preservation. The staged adapter permits cleanup of an exact, fully accounted synthetic clone with no dispatch intent. Require a durable integration ref that retains the exact predecessor commit. The controller binds that ref and its target in the cleanup intent and rechecks their identity and reachability under the integration guard immediately before removal. A lost, changed, or ambiguous ref holds cleanup and retains the clone. Previously dispatched or otherwise uncertain generations stay retained.

Before removal:

1. Verify the intended source commits and original diffs are retained in the authorized repository or a recoverable archive.
2. Preserve raw test and failure evidence in the private evidence store. Check its recovery references.
3. Account for tracked changes, untracked files, ignored files, generated files, and external dependencies.
4. Confirm no active writer, replacement attempt, or dependent task still needs the worktree or its files.
5. Verify the retained revision and evidence can be read back. Preserve ambiguous or irreplaceable local files.

Remove only the completed worktree and artifacts demonstrated to be regenerable or durably retained. Do not force-remove unknown work. Delete branch refs only when separately authorized and required history remains reachable.

Record the retained source, evidence location, cleanup result, and measured reclaimed space. A cleanup blocker does not erase local acceptance, but it remains unfinished cleanup.

Repository visibility follows actual owner direction. Keep private evidence and credentials outside public source repositories.

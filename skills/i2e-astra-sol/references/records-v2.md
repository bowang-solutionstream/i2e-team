# V2 runtime records

New Critical work uses the [four-round Critical workflow](critical-four-rounds.md). The v8 procedures below cover Direct, Standard and replay of runs already recorded under the earlier profile.

Use UTF-8 JSON records with unique keys. Evidence references contain absolute `path` and actual `sha256`. Use literal project-relative source paths, actual Git identities, and fresh ledger sequence. See the [public commands](runtime.md).

## Intake and policy

| Record | Required fields |
|---|---|
| `run init` | `schema` (`i2e-team-run-v2`), `profile` (`i2e-team/v2`), `run_id`, `project`, `repo`, `scope`, `test_scope`, `instructions`, `contributors`, `authority`, `policy`, `case_store`, `case_helper`, `case_helper_sha256`, `known_cases`, `objective`, `parent_request`, `tickets`, `write_boundary`, `source`, `executor_mode` (`macos-sandbox-full-clone-v1`), `synthetic` |
| Policy | `schema` (`i2e-team-policy-v2`), `queue_priority`, `technical_risk`, `execution_lane`, `significant_architecture`, `triggers`, `direct_eligible`, `reproducible_acceptance`, `specialists` |
| Authority | `actions` and `evidence` |
| Ticket | `id` and nonempty `acceptance` list |
| Source | `base`, immutable `harness` and `dependencies` path lists |
| Write boundary | literal `test`, `production`, and `excluded` lists, with optional `surfaces` rows `{path, kind, role, ticket}` |

Intake optionally accepts `coordinator`, `delivery`, and `rollback`. `repo` is the actual Git root and `source.base` is its full HEAD commit. Harness and dependency paths are disjoint subsets of the immutable `instructions`. A dependent source may add `predecessor` with `run`, `prefix`, `candidate`, `commit`, and `acceptance` reference. Use the exact accepted predecessor in the same ledger.

Policy optionally accepts `assurance`, `routine_worker`, and `tier_policy`. The combined `assurance` assessment has `ticket_count`, `clear_authority`, `bounded_scope`, `observable_acceptance`, `adequate_regression`, `interaction_coverage`, and named `checks` of `{state, reason}`. Reduced lanes require complete eligible evidence. For a routine assignment in Direct or Standard, set `routine_worker.model` to `gpt-6.2-sol`, list literal owned `paths`, and set `bounded` to `true`.

Supply all seven boolean `triggers`: `consequential_authorization_or_tenant`, `destructive_migration`, `critical_financial_behavior`, `uncertain_cross_system_interaction`, `material_redesign`, `conflicting_reviews`, and `user_or_project_requirement`.

An observed actor has `session`, `model`, `effort`, `evidence`, `requested_tier`, and `observed_tier`. `evidence` points to the actual invocation artifact from `rollout`. Record a preceding `observation` with `kind: ROUTING`, observed `probe` and `owner`, and `lead` for Standard or Critical. The `record_unknown` tier policy requires a preceding actual owner `human_decision` with `kind: TIER_POLICY`, `actor: human`, `policy`, `source`, `statement`, and session-keyed `alternates`. See [policy](policy.md).

## Plan and phase events

`run append` takes `{id, type, data}`. The controller records sequence and prefix. Use typed public calls for starts, proof, case links, worker, and delivery events. Internal `i2e/` IDs and their operation event types are reserved.

A `plan` has `data` with `revision`, `content`, `consultation`, and `supersedes`. The revision is the SHA-256 of canonical `content`. `consultation` names the preceding plan consultation targeting this plan event ID. `supersedes` is the immediately preceding plan revision or `null` for the first plan.

`content` requires `artifact`, `scope`, `test_scope`, `acceptance`, `checks`, `required_checks`, `result_map`, `aggregate_checks`, `decisions`, `decision_reason`, `contributors`, `policy`, and `remediations`. It optionally accepts `batch`, `expected_files`, `rollback`, `delivery`, and `verification_map`.

- Each `acceptance` row has `id` and boolean `behavior`. Justify `behavior: false` with `reason`.
- `result_map` maps acceptance IDs to `{check, test, production}`. Map each acceptance to a distinct required check and its exact owned test and production paths.
- `verification_map` maps a behavioral acceptance to `{test_path, test_id, command, runner}`. `runner` records the canonical executable `path` and `sha256`. The mapped CHECK uses the exact test path, native identity, runner, and command.
- `aggregate_checks` maps required aggregate check IDs to the required acceptance IDs.
- Each remediation has `findings`, `defects`, `scope`, `acceptance`, `checks`, and `case_pairs`. Each case pair is `{digest, check}`. A named High remediation also records the observed `repair_actor`.
- `batch` has `allowed_subsets`, `subset_delivery`, `dependencies`, and `interaction_checks`. A recorded removal uses `batch_membership` with `plan`, `previous`, `members`, `candidate`, `continuations`, and `reason`. A receiving lane `handoff` records `prior_plan`, `target_lane`, `candidate`, `defect`, `prior_actor`, `next_action` (`PLAN_REVIEW`), and `reason`.

`preflight` takes `id` and `acceptance`. Optional fields are `repair_defect`, `remediation`, `observe_manifest`, and `write_manifest`. The CLI supplies `--mode VERIFY|TEST_ONLY|PRODUCTION`. `observe_manifest` belongs to VERIFY with empty `write_scope` and `write_manifest`. A later write phase uses current exact `write_manifest` rows.

A bounded preflight's `remediation` repeats the exact plan mapping and adds `before` and `reason`. For a named High finding, include the exact observed Sol `repair_actor` on new runs and the originally routed actor on historical runs inside that matching remediation. The actor owns only the affected TEST_ONLY and PRODUCTION starts and their dependent proof or worker operations. VERIFY and unrelated work keep the ordinary routed owner.

Each manifest row has `path`, `ticket`, `role`, `baseline`, and `impact`. `baseline` is the observed SHA-256 or `null` for absence. `impact` has `callers`, `dependencies`, `checks`, `technical_risk`, and `contract_unchanged`. The controller adds physical identities and the full candidate. See [execution](execution.md) for precedence and phase order.

## Controller observations

The controller records v2 source snapshots with `repo`, `files`, `instructions`, `modes`, and `sha256`. The byte maps retain their SHA-256 values and use `null` for an absent owned file. The `modes` map covers the exact union of the two byte maps. Each absent file has mode `null`. Each present regular file has Git mode `100644` or `100755`, selected by the owner's execute bit. The controller refuses unsupported file types, special permission bits, and inconsistent observations. The snapshot digest covers the canonical body including the mode map. V1 retains its byte-only snapshot and digest.

The controller derives modes from actual observations, including the first candidate and physical record for an added path. Intake and manifest requests keep their existing fields. The generated `source` in starts and proof records retains `base` and the harness and dependency byte maps. Its `modes` covers exactly those harness and dependency paths. The full candidate carries all instruction modes.

## Proof, review, and case requests

| Request | Fields |
|---|---|
| Command `proof` | `id`, `phase`, `check`, `start`, `actor`, and literal `command`, with optional `timeout_seconds`. `actor` is the observed session ID. |
| RED, GREEN, or mapped CHECK | Command fields plus `acceptance`, `test_id`, and `test_path`. RED also requires `failure_kind: ASSERTION`. |
| Aggregate CHECK | `id`, `phase: CHECK`, `check`, `start`, `actor`, and exact `results` array of `{acceptance, proof}`. |
| `case consult` | `id`, `stage` (`plan`, `repair`, or `final`), `target`, `query`. An exact recovery may include `recovery_for` and `recovery_reason`. |
| `case capture` | `id`, `defect`, canonical `case`, and `failure` with `command`, `output`, `inputs`, `broken`, and `broken_files`. |
| `case bind` | `id`, `digest`, `check`, `defect`, `failure`, `case_link`, `consultation`, `before`, `plan`, `prior_run`, `prior_prefix`, and `relation` with `source` reference and `reason`. |

Use the same native selection form for a behavioral proof request and its verification map entry. Replace the example executable paths with the observed canonical runner paths. Record each actual runner digest in the map.

| `test_path` | `test_id` | `command` |
|---|---|---|
| `behaviors_test.py` | `Behaviors.test_A1` | `["/absolute/path/to/python3", "-B", "behaviors_test.py", "Behaviors.test_A1", "-v"]` |
| `behaviors.test.cjs` | `A2W labels recorded and missing telemetry` | `["/absolute/path/to/node", "--test", "behaviors.test.cjs"]` |

Append a `case_decision` for each shown digest with `consultation`, `digest`, `applicability`, and `reason`. `APPLIES` also requires the named `checks`. `failure_classification` binds `attempt`, `defect`, `kind`, and `reason` to an actual failed proof attempt.

A typed review contains `reviewer` with `session`, `model`, `effort`, `fresh`, `excluded`, and `input`, `invocation`, and `response` evidence references. It binds the applicable exact plan, decision, or candidate and findings. A finding records `id`, `actionable`, `material`, `text`, `severity`, `requirement`, `evidence`, `consequence`, `correction`, and `validation` check. Audits record `executed` results with `check`, `argv`, `exit`, `candidate`, `stdout`, and `stderr`, plus `inspected` source paths and any `specialists`. See [verification](verification.md).

## Worker and delivery requests

Every worker request has `id`, `actor`, and `attempt`. `prepare` adds `ticket`, `start`, `predecessor`, and `mode`. `run` adds `command`. `revoke` adds `reason`. `submit` adds `commit`. `admit` adds `submission`. `cleanup` adds `retained_commit`. `qualify` and `status` take the common fields. The controller derives the generation, integration ref, and admission records. Use synthetic authority containing `edit` and `worker`. Cleanup additionally requires `cleanup`. For pending admission readback, repeat the original request and its original expected sequence.

The immutable `delivery` boundary contains `repository`, `target`, `pr`, `action` (`merge_commit`), `actor`, `trusted_check` (`name` and `app_id`), `rules_admin_trust`, and `authority` reference. Intake must authorize `merge_github`. `inspect` and `prepare` take `id`, `repository`, `target`, `pr`, `head`, `base`, `candidate`, `actor`, `action`, and `authority`. `execute` and `reconcile` take `id`, `operation`, `actor`, and `authority`. `operation` is the durable returned intent ID. See [delivery](delivery.md) for provider and reconciliation limits.

The controller derives `membership` as `{event, members, continuations}`. Full intake uses `event: null`, the intake ticket list, and an empty continuation map. A subset uses the selected live membership event's `{id, sha256}` and its exact members and continuations. The trusted-check receipt and the durable intent's local binding carry this record and the mode-bearing candidate digest. The dispatch binds the intent digest.

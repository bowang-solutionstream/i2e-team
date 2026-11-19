# Critical engineering in four rounds

Use this workflow for a new High or Critical technical risk or significant architecture decision. A Sol coordinator screens the request and records the user's objective, write authority, known failures and acceptance. Round 1 can supply the evidence needed to classify the work. The first successful pass uses four agent assignments.

| Round | Assignment | Handoff |
|---|---|---|
| 1 | Sol 6.2 Max · Fast | Probe the target checkout read-only. Record the baseline, affected entrypoints, known cases, available lint and E2E commands, dependencies and unknowns. |
| 2 | Astra 6.2 Max · Standard | Use Spec Kit in the private session workspace. Write the specification, design, measurable acceptance and local development issues in one session. |
| 3 | Sol 6.2 Max · Fast | Implement the accepted local issues in dependency order. Record focused regression evidence, material failures and the integrated candidate. Sol owns repairs at every severity. |
| 4 | Fresh Sol 6.2 Max · Fast | Independently run the full project lint and E2E commands on the integrated candidate. Check every accepted criterion and record its observed outcome. |

Astra's Critical assignment ends at the planning handoff. Configure round 2 with network access disabled for commands, no publishing connectors and write access limited to its private planning workspace and run receipts. Read the target via the read-only probe or a read-only checkout. Keep specifications, task IDs and status changes local for the entire run. Astra plans from local snapshots in its network-disabled workspace. Publishing the reusable skill is a separate maintainer action.

## Prepare the session

Use Python 3.11 or later and an existing Git checkout. Set `repo` to its root and `private_root` to an owner-only directory outside both that checkout and the installed skill. A distinct directory per run keeps two sessions' T001 issues independent. Set `i2e` to the installed or unpacked `scripts/i2e.py`.

```sh
mkdir -p "$private_root"
run=$(mktemp -d "$private_root/critical.XXXXXXXX")
state="$run/run.json"
intake=$(python3 -B "$(dirname "$i2e")/fetch_library.py" "$run") || exit 1
library="$intake/library"
cat "$intake/catalog.json"
python3 -B "$i2e" critical routing
python3 -B "$i2e" critical --state "$state" init --repo "$repo"
python3 -B "$i2e" setup-speckit --workspace "$run/planning" > "$run/setup.json"
```

Prepare Spec Kit before dispatch. The bootstrap uses a matching installed `specify` CLI, or `uv` to install the pinned upstream version. It initializes the three planning skills from bundled assets with events disabled. Prepare the pinned CLI while online if the planner will run offline. Each run uses its own planning workspace. See the [Spec Kit Codex integration](https://github.github.io/spec-kit/integrations/codex.html).

Use real, persisted Codex rollouts. Launch each actor at its assigned model and effort. Fast uses `service_tier="priority"`. Standard uses `service_tier="default"`. If native children inherit the coordinator's speed, launch Astra as a separate Standard root. Launch the verifier as a new standalone Sol session **after** the implementation handoff. Give it the frozen candidate, accepted specification, known regressions and verification commands. Let it form its own assessment. Give actors access to write their private receipts. Give only the implementer authority to edit product source.

## Probe and plan

Run `critical --state "$state" probe --rollout "$sol_log" --evidence "$probe"` with the read-only probe's findings. Astra must supply its local-only launch record. Sol supplies `--dispatch PATH` when the host rollout omits the requested tier. The private dispatch record contains `session` and the actual Codex launch `argv`, including `--model`, `model_reasoning_effort` and `service_tier`. Preserve what the host actually reports. The controller reports the effective provider tier as unknown when it cannot establish it.

Start Astra with the `planner_argv` from setup. It selects the private planning workspace, disables command networking, connected apps, plugins and web search, and omits user-configured MCP servers. Pass the probe and assignment on stdin. Capture the launch arguments and real session ID for the handoff.

```sh
python3 -c 'import json, os, sys; argv = json.load(open(sys.argv[1]))["planner_argv"]; os.execvp(argv[0], argv)' \
  "$run/setup.json" < "$run/planning-assignment.md" > "$run/planner-events.jsonl"
```

Invoke `$speckit-specify`, `$speckit-plan` and `$speckit-tasks` in that one session. Keep all three artifacts in the same private `specs/<feature>/` directory. Include observable success and failure criteria such as `- **SC-001**: A new checkout lists only its own local issues.` In `plan.md`, identify the implementation boundary, dependencies, real lint and E2E entrypoints, expected outcomes and handling of known regressions. In `tasks.md`, use ordinary Spec Kit checkboxes such as `- [ ] T001 [US1] List local issues`. Put dependencies and acceptance IDs on indented lines. Plan only the authorized work.

```sh
python3 -B "$i2e" critical --state "$state" plan --rollout "$astra_log" --dispatch "$astra_dispatch" \
  --spec "$feature/spec.md" --plan "$feature/plan.md" --tasks "$feature/tasks.md" \
  --lint-argv "$lint_argv_json" --e2e-argv "$e2e_argv_json"
python3 -B "$i2e" critical --state "$state" tasks
```

Pass JSON arrays of executable arguments. Use the repository-wide lint command and an E2E command that exercises the real user journey and asserts visible results. For a service, start or target its authorized test instance. For a CLI, invoke its actual entrypoint with representative inputs and check outputs and failure behavior. Record unavailable prerequisites as blockers. The handoff freezes a digest of the plan and a snapshot of every local issue under `run.json.d/issues/`.

## Implement and verify

Sol can reuse its probe context. Track the current issue locally with `critical --state "$state" task --id T001 --status IN_PROGRESS`, then `DONE` when its work is ready. `OPEN` reopens it. Inspection and focused regression checks can run during implementation. A checked box records progress. Acceptance requires the final evidence.

```sh
python3 -B "$i2e" critical --state "$state" implement --rollout "$implementer_log" --evidence "$handoff"
python3 -B "$i2e" critical --state "$state" verify --rollout "$verifier_log"
python3 -B "$i2e" critical --state "$state" status
```

The verifier runs `verify` and `accept` inside its own session. The controller executes the two pinned commands, stores both output streams and their exit codes, and checks that the candidate and plan still match. Inspect the covered journeys, assertions and affected source. Use the returned `plan_sha256`, `candidate_sha256` and `verification_sha256` in the acceptance JSON. Include one `cases` entry per accepted ID with `id`, `verdict` (`PASS` or `FAIL`), `check` (`lint`, `e2e` or `inspection`) and a specific `observation`. Record gaps and failed criteria honestly.

```sh
python3 -B "$i2e" critical --state "$state" accept --rollout "$verifier_log" --acceptance "$acceptance_json"
python3 -B "$i2e" critical --state "$state" status
```

Failed checks or acceptance return the same design to Sol for repair. A new independent Sol verification follows on the repaired candidate. One repair and recheck bring the total to six assignments. Return to Astra only for a material change to the accepted design or criteria. Record the change through `plan --replan-reason` and retain prior snapshots. Report local verified acceptance at the exact candidate separately from any release decision.

## Shared library at intake and handoff

Before every new I2E run and whenever a later session resumes one, the coordinator fetches the latest merged properties and rules from `main`. Do this before project inspection, planning, dispatch or edits, including read-only runs. Set `run` to the private run directory outside the product, and `skill` to the directory of the active skill containing `scripts/fetch_library.py`.

```sh
intake=$(python3 -B "$skill/scripts/fetch_library.py" "$run") || exit 1
library="$intake/library"
cat "$intake/catalog.json"
```

The installed parser validates records directly from the fetched Git objects. Continue only when the command succeeds. Record the returned snapshot path, the `revision` in `catalog.json` and the relevant record IDs. Read the matching Markdown in `library/properties/` and `library/rules/`. A failed fetch or invalid catalog blocks the run. Report the failure and retry the fetch before continuing. Earlier receipts remain evidence of earlier work. Keep the same snapshot across rounds of this invocation. On resumption, retain the previous receipt and reconcile newly applicable checks with the plan before continuing.

The Critical preparation commands above already fetch once. Sol supplies the selected properties and triggers to Astra locally. Astra's Spec Kit planning stays offline. Adopted properties provide scoped oracles and adopted rules supply diff checks. Treat candidates as suggestions and skip retired records.

At successful handoff, the coordinator inspects verified outcomes for newly demonstrated properties and misses. Run reflection only after the requested delivery succeeds. For Critical work this includes fresh Sol's passing lint, E2E, accepted criteria, `phase=complete` and `acceptance_current=true` on the final candidate. This handoff uses the existing coordinator and adds no agent round. Failed, partial, stale and read-only runs retain observations privately.

Create an empty private drafts directory. For each new public-safe finding copy a property or rule template from the pinned library to the matching draft folder. Provide an independent oracle for a property or a diff trigger, check and observed failure for a rule. Submit new entries as candidates. For another observation of an existing definition, append a distinct public-safe `seen-in`. Inspect exact text before publication. Keep all project evidence, private identifiers and session issues local.

```sh
mkdir -p "$run/drafts/properties" "$run/drafts/rules"
python3 -B "$library/tools/library.py" reflect --workflow i2e-astra-sol \
  --entries "$run/drafts" --i2e "$i2e" --state "$state"
```

For Direct or Standard use `--db "$db" --run "$run_id"` in place of `--state "$state"` with that run's controller. The owner authorizes sanitized entries on `i2e-property-libraries` or `i2e-misses-to-rules` and their merge to `main`. Record `MERGED` with commit and IDs or `NO_CHANGES`. For `PENDING` or `BLOCKED`, keep the drafts, identify the publication gap independently of delivery, and retry once resolved. Shared candidate publication, adoption and project enforcement are separate actions. The [canonical library guide](https://github.com/bowang-solutionstream/i2e-team/blob/main/README.md) covers acceptance evidence, privacy, deduplication and adoption.

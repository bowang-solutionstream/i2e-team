# Staged v2 runtime

New Critical work uses the [four-round Critical workflow](critical-four-rounds.md). The v8 procedures below cover Direct, Standard and replay of runs already recorded under the earlier profile.

Profile `i2e-team/v2` · revision `v8` · status `STAGED_NOT_INSTALLED`.

Use Python 3.11 or newer with the bundled [controller](../scripts/i2e.py) and its sibling modules. Native proof and synthetic workers require the qualified macOS executor. For existing v1 records, use the preserved [v1 runtime guide](runtime-v1.md). Native v1 certification remains `BLOCKED_NOT_CERTIFIED`.

Keep the SQLite ledger, evidence, authority records, and case store in private storage outside the source and package. Read [storage settings](settings.md) for existing locations. Choose the exact ledger and case helper explicitly for each run. `shared_cases.py` comes from the external canonical `i2e-failure-cases` skill. Pin its actual path and SHA-256. The archive contains neither the helper nor its records.

## Command interface

Run `python3 -B <skill>/scripts/i2e.py --help` for the command list. For an authorized isolated exercise, set `i2e_script` to that file and `i2e_ledger` to the fixture ledger. The following templates take input records described in [records-v2](records-v2.md).

```sh
python3 -B "$i2e_script" policy --input policy.json
python3 -B "$i2e_script" run init --db "$i2e_ledger" --input intake.json
python3 -B "$i2e_script" run show --db "$i2e_ledger" --run "$i2e_run"
python3 -B "$i2e_script" run search --db "$i2e_ledger" --project "$i2e_project" --query "$i2e_query"
python3 -B "$i2e_script" run append --db "$i2e_ledger" --run "$i2e_run" --expect "$i2e_seq" --input event.json
python3 -B "$i2e_script" preflight --db "$i2e_ledger" --run "$i2e_run" --expect "$i2e_seq" --mode VERIFY --input start.json
python3 -B "$i2e_script" proof --db "$i2e_ledger" --run "$i2e_run" --expect "$i2e_seq" --input proof.json
python3 -B "$i2e_script" check --db "$i2e_ledger" --run "$i2e_run"
python3 -B "$i2e_script" brief --db "$i2e_ledger" --run "$i2e_run"
```

`--input -` reads JSON from stdin. `run show` returns the current `seq` and ledger prefix `sha256`. Reload before each new mutation and use the exact sequence in `--expect`. Read both exit and the returned operation state. Preserve a `BLOCK` or `HOLD` receipt and pause its dependent action. A preflight PASS supplies only its recorded phase and write scope.

Historical v2 snapshots without `modes` remain readable in `run show`. A missing historical mode is unknown and holds live authority, proof, and current acceptance when required by the operation. Resume through a new explicitly authorized v2 run with fresh mode-bearing intake, applicable case consultation, and genuine proof. Preserve the original records and digests as recorded.

| Command | Operation |
|---|---|
| `rollout --log` | Extract host-recorded actor identity into a private invocation artifact. Retain and inspect the actual source log and exclusions. |
| `case consult`, `case capture`, `case bind` | Call the configured canonical helper, record consultation or local capture, or bind an inherited case to reviewed remediation. |
| `worker prepare`, `qualify`, `run`, `status`, `revoke`, `submit`, `admit`, `cleanup` | Operate on the exact attempt in the supported synthetic adapter. |
| `delivery inspect`, `prepare`, `execute`, `reconcile` | Inspect candidate and target, prepare and execute an authorized synchronous merge, or reconcile an existing dispatch. |

`rollout` takes `--db`, `--run`, and `--log`. Case, worker, and delivery requests use `--db`, `--run`, `--expect`, and `--input`. Inspect `worker --help` and `delivery --help` safely. Operational delivery requires actual authorized provider access and target qualification. Local delivery checks use an offline fake.

## Record order

1. Confirm authority and use `policy` to evaluate lane and requested settings. Initialize the explicit v2 run and record host identities with `rollout`. Consult cases for the named plan event before the plan is appended.
2. Record actual routing, the immutable plan and acceptance, decision support, and any required exact-plan review. Use separate eligible reviewers. See [policy](policy.md).
3. Establish current checks and observe extra paths in VERIFY. Request TEST_ONLY for tests, capture intended assertion RED, refresh applicable checks, and obtain PRODUCTION before production writes. Record unchanged-test GREEN and exact mapped and aggregate results. See [execution](execution.md) and [verification](verification.md).
4. Resolve findings and case regressions. Record current independent reviews and any required final review. Use [delivery](delivery.md) for exact handoff and reconciliation.
5. Run `check` for `ready` on the current candidate. Record the actual status report, then its linked engineering brief. Use `brief` and `check` to inspect the completed report and evidence. Read `lifecycle`, `parent_complete`, and continuation records before reporting completion. An accepted subset can leave its parent open.

The controller validates record order, identity and proof. Independent review checks the actual authority, source, assertions, and evidence limits. For the staged evaluation and later host or target qualification, see [adoption](adoption.md).

# Using the I2E v8 skill

Open this checkout in Codex and invoke `$i2e-astra-sol`. The [discoverable entry point](../.agents/skills/i2e-astra-sol/SKILL.md) loads the [canonical skill](../skills/i2e-astra-sol/SKILL.md). Its [routing policy](../skills/i2e-astra-sol/references/policy.md) specifies Sol 6.2 Max and Astra 6.2 Max. Direct, Standard and Critical work retain their own approval and review requirements.

The trusted checkout registers two Codex role presets in `.codex/config.toml`. For a user-level installation, copy `agents/i2e_team_sol.toml` and `agents/i2e_team_astra.toml` from the skill package to the Codex user `agents/` directory and open a fresh session. Under a Fast coordinator, launch Astra in a separate Standard session when the host inherits the root tier. The [dispatch examples](../skills/i2e-astra-sol/references/policy.md#requested-settings-and-evidence) include both read-only commands.

## Select verification for a feature

Use Python 3.11+ for the selection CLI. From the repository root, this command selects Chrome DevTools MCP, fast-check and the shared label catalog.

```sh
python3 -B skills/i2e-astra-sol/scripts/i2e.py select-tools --surface web --language typescript --feature labels.normalize
```

For another feature, save its catalog in version control. Run the same selector from the checkout containing the catalog and pass `--feature FEATURE --catalog PATH`. The [catalog contract and promotion procedure](../skills/i2e-astra-sol/references/verification.md#project-catalogs-and-rule-promotion) defines the fields. Bind the selected file, project verifier and lockfile to the plan. The project verifier runs the actual journey, checks its properties and records observe-mode and enforced rule outcomes.

## Replay the web pilot

Use Node 22.12+, npm, Python 3.11+ and a local Chrome installation. Set `CHROME_EXECUTABLE` if Chrome needs an explicit path. Choose a new output directory outside the checkout. The following commands use a POSIX shell.

```sh
run_dir="$(mktemp -d)"
python3 -B scripts/pilot_web_labels.py --output "$run_dir/web"
```

The [project verifier](../examples/typescript-labels/.agents/skills/verify/SKILL.md) compiles a fresh TypeScript build, submits the real form in isolated headless Chrome and uses fast-check on the same compiled function. The pilot exercises working code, UI order, Unicode spelling, replay of the reduced input and missing Chrome. It also runs a checkout catalog against a spelling fault that both the browser and generated checks miss. First observe the discrepancy, then enforce the same example and replay the working implementation. Each run saves its selection, streams and exit under the output directory.

## Package and verify

From the repository root, use a fresh private output location.

```sh
run_dir="$(mktemp -d)"
python3 -B scripts/package_v2.py stage --source skills/i2e-astra-sol --dest "$run_dir/package"
python3 -B scripts/package_v2.py verify --package "$run_dir/package" --extract "$run_dir/readback"
python3 -B scripts/pilot_web_labels.py --skill "$run_dir/readback/i2e-astra-sol" --output "$run_dir/web"
```

The Python controller pilot and native regression suite use macOS, Python 3.12+, Git, Node and the separate canonical case helper at `~/.codex/skills/i2e-failure-cases/scripts/shared_cases.py`. The [pinned helper source](https://github.com/bowang-solutionstream/i2e-chat-astra-sol/blob/241f210a818a3675608b46366045bd33b9dd383c/skills/i2e-failure-cases/scripts/shared_cases.py) identifies the tested dependency. The web pilot and selection CLI work independently of the private case store. For the controller exercise, `scripts/pilot_labels_v8.py --help` lists the explicit helper and output options. Its local ledger uses synthetic actors. Run the I2E tests on a host with these prerequisites.

```sh
for pattern in 'test_i2e*.py' 'test_*verification*.py' 'test_four_behavior_repair.py'; do
  python3 -B -m unittest discover -s tests -p "$pattern" -v || exit 1
done
```

The [adoption guide](../skills/i2e-astra-sol/references/adoption.md) defines the evidence needed for operational agent transport, host selection and delivery. Private run records, case-store contents and machine settings stay with the operator.

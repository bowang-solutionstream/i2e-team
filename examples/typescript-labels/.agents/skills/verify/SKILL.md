---
name: verify
description: Verify the disposable TypeScript label form, its normalizeLabels function and learned label rules using the staged I2E tool selection.
---

Run from the fixture's package root with Python 3.11+, Node 22.12+, npm and a local Chrome installation. Set `CHROME_EXECUTABLE` when the driver needs the path to Chrome. In a fresh clone of the staged repo the fixture is under `examples/typescript-labels`. The project skill, source, test commands and dependency lock travel together.

Set `i2e_skill` to the pinned staged skill directory. From the example's original location, use `i2e_skill=../../skills/i2e-team`. In a disposable copy, point it to that checkout or its verified package readback. At planning, create the tool selection once and bind it, this harness, the dependency lock and the selected catalog to the candidate's verification plan.

```sh
python3 -B "$i2e_skill/scripts/i2e.py" select-tools --surface web --language typescript --feature labels.normalize > tool-plan.json
npm ci --include=dev --ignore-scripts --no-audit --no-fund
npm run --silent verify -- --plan tool-plan.json --catalog "$i2e_skill/references/label-verification.json"
```

The verifier builds the TypeScript, serves the fixture on loopback, launches the locked Chrome DevTools MCP over stdio with an isolated headless profile, fills the form, clicks Normalize and reads the ordered results. The property check uses fast-check on the same compiled export. The shared catalog supplies the examples and enforcement status for learned rules. Save stdout, stderr and exit in the run directory. Exit 0 means all required checks ran and passed, 1 indicates a behavioral failure, and 2 indicates a verifier setup or transport error. A failed install or build leaves the run unverified.

For a checkout catalog, select `labels.normalize` with `--catalog`. This verifier implements entry point `normalizeLabels` and checks `labels.form.e2e` and `labels.normalize.properties`. Use arrays of strings for label-rule inputs and expected values. Observe-mode rules report discrepancies. Enforced rules contribute to the exit status.

Keep the original plan and lock for replay. The property receipt includes a seed and the reduced failure path. Add `--seed NUMBER --path PATH` to the same verify command to replay the generated failure with the pinned library. For a new miss, retain the reduced input and observed output privately and follow the staged catalog's rule-promotion procedure.

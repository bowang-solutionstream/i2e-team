# I2E Team

The `i2e-astra-sol` branch contains the Astra and Sol Issue-to-Edit workflow. Open the checkout in Codex and invoke `$i2e-team` with the task you want to deliver.

| Critical round | Agent | Responsibility |
| --- | --- | --- |
| 1 | Sol 6.2 Max · Fast | Probe the checkout read-only and identify the affected behavior. |
| 2 | Astra 6.2 Max · Standard | Use Spec Kit to define the deliverables, acceptance criteria and session-local issues. |
| 3 | Sol 6.2 Max · Fast | Implement the agreed issues and hand off the integrated candidate. |
| 4 | Fresh Sol 6.2 Max · Fast | Run the agreed full lint and end-to-end checks, then record an observation for every acceptance criterion. |

## Start on another machine

With Git and Python 3.11 or later, clone the branch and check its routing.

```sh
git clone --branch i2e-astra-sol https://github.com/bowang-solutionstream/i2e-team.git
cd i2e-team
python3 -B skills/i2e-team/scripts/i2e.py critical routing
```

Keep the planning workspace and issue board in a private directory outside the checkout. The [Critical workflow guide](skills/i2e-team/references/critical-four-rounds.md) covers Spec Kit setup, handoffs, repair and verification. The [verification guide](docs/I2E-V8-VERIFICATION.md) covers the package, test commands and dependencies for the full regression suite.

The skill, role presets, examples and tests on this branch come from the [verified source revision](https://github.com/bowang-solutionstream/utlyze-agent-memory/commit/f602be2c51785e1c7bb52ecc54973cedf189267b).

All three model workflows read the [merged property and rule library](https://github.com/bowang-solutionstream/i2e-team/tree/main). After successful delivery, the coordinator publishes new public-safe findings to their category branches and merges them into the catalog for the next run.

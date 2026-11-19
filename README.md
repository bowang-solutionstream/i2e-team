# I2E Team

The `i2e-fable-opus` branch contains the Fable and Opus Issue-to-Edit workflow for
Claude Code. Install it, then invoke `/i2e-fable-opus` with the issue, pull request,
or change you want delivered. Each workflow in this collection has its own branch:
[`i2e-opus-sonnet`](https://github.com/bowang-solutionstream/i2e-team/tree/i2e-opus-sonnet)
holds the Opus and Sonnet workflow for Claude Code, and
[`i2e-astra-sol`](https://github.com/bowang-solutionstream/i2e-team/tree/i2e-astra-sol)
the Astra and Sol workflow for Codex.

| Step | Agent | Responsibility |
| --- | --- | --- |
| 1 | Opus 5.5 Max working session | Set the contract, find the repository's verification assets, and look up matching library entries. |
| 2 | Fresh Fable 5.2 Max planner | Write the plan and test strategy, and flag hard-to-reverse decisions. |
| 3 | Fresh Opus 5.5 Max doubt reviewer | Challenge a flagged decision, only after you approve the review. |
| 4 | Opus 5.5 Max working session | Implement with test-first, property, and end-to-end proof on the running system. |
| 5 | Fresh Opus 5.5 Max security auditor | Audit the change, only when it touches a trust boundary. |
| 6 | Fresh Fable 5.2 Max reviewer | Give the main code review; later rounds look at the change since the last round. |

Before any doubt review, the session tells you which decision it would check, why a
review is needed, and what the reviewer would examine; only the reviews you approve
run. At the end, the session reports what was proven, adds what it learned to the
shared library as candidates, and merges public-safe findings into the shared catalog at successful handoff.

The workflow is built on engineering practices from
[Addy Osmani's agent-skills](https://github.com/addyosmani/agent-skills). Credit to
Addy Osmani for the foundational engineering skillset; this branch adapts those
practices into a standalone Issue-to-Edit workflow. It is an independent adaptation,
not an official upstream release or endorsement.

## Start on another machine

You need Git, Python 3.10 or later, and Claude Code with subagent support and access
to `claude-fable-5-2` and `claude-opus-5-5` at `max` effort.

```sh
git clone --branch i2e-fable-opus https://github.com/bowang-solutionstream/i2e-team.git i2e-fable-opus
cd i2e-fable-opus
python3 scripts/install.py
python3 scripts/install.py --check
```

The installer copies the skill to `skills/i2e-fable-opus` and its subagent
definitions to `agents/i2e-fable-opus` inside `$CLAUDE_CONFIG_DIR`, or `~/.claude`
when that is unset, so every Claude Code session can use them. It has no third-party
dependency, does not contact the network, and changes no settings. Start a new
Claude Code session afterwards to load the skill and agents.

## The shared property and rule library

All three I2E workflows fetch the latest merged catalog from [main](https://github.com/bowang-solutionstream/i2e-team/tree/main) at intake. After successful delivery, the coordinator publishes public-safe properties and lessons from observed misses to their category branches and merges them into the catalog. A run with no new findings creates no commit. The [library guide](skills/i2e-fable-opus/references/library.md) covers the commands, evidence and retry behavior.

## Update

```sh
git pull --ff-only
python3 scripts/install.py --update
python3 scripts/install.py --check
```

Identical installs are no-ops. A different existing installation is refused unless
`--update` is given; each replaced bundle is kept under a timestamped run in
`.i2e-fable-opus-backups` inside the Claude config directory, and the installer
prints the backup path. If an installation fails partway, the installer puts back
what it replaced. `--dry-run` previews without writing, and `--check` is read-only.

## Maintain and validate

Edit the sources under `skills/`, not an installed copy, and do not edit the pinned
guides under `skills/i2e-fable-opus/references/lifecycle/`. The `scripts/`,
`tests/`, and `library-template/` folders and the skill's `references/library.md`
are shared with the `i2e-opus-sonnet` branch: make the same change on both branches.

```sh
python3 scripts/validate.py
python3 -m unittest discover -s tests -v
git diff --check
```

The validator checks the skill's structure and metadata, its exact subagents with
their pinned models, effort, tool, and deny lists, the lifecycle snapshot against
its manifest, the library guide, and local links. The tests cover the installer,
validator, and library tool; the tests for the `i2e-opus-sonnet` skill are skipped
on this branch. These checks do not establish model quality or cost savings; see
[validation evidence](docs/validation.md). An optional
[GitHub Actions template](docs/github-actions-validate.yml) runs the same checks.

## Credits and license notices

- [Addy Osmani's agent-skills](https://github.com/addyosmani/agent-skills) provides
  the foundational practices, the 25 lifecycle guides bundled with the skill, and
  the reviewer roles. Its MIT license is retained in
  `skills/i2e-fable-opus/notices/`.
- [Pattern, Inc.'s code-mint](https://github.com/patterninc/code-mint) contributed
  the issue-refinement guidance; its Apache 2.0 license is retained in the same
  folder.
- The verification practices adapt Addy Osmani's
  [How the Claude Code team thinks about verification](https://claude.dev/blog/how-the-claude-code-team-thinks-about-verification/).

The skill's [NOTICE.md](skills/i2e-fable-opus/NOTICE.md) records source revisions
and adaptation details. No repository-wide license is declared for the original
orchestration and tooling, and this adaptation does not relicense them. This branch
continues the `bowang-solutionstream/i2e-fable-opus` repository.

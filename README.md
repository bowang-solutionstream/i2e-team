# I2E Team

The `i2e-opus-sonnet` branch contains the Opus and Sonnet Issue-to-Edit workflow for
Claude Code. Install it, then invoke `/i2e-opus-sonnet` with the issue, pull
request, or change you want delivered. Each workflow in this collection has its own
branch:
[`i2e-fable-opus`](https://github.com/bowang-solutionstream/i2e-team/tree/i2e-fable-opus)
holds the Fable and Opus workflow for Claude Code, and
[`i2e-astra-sol`](https://github.com/bowang-solutionstream/i2e-team/tree/i2e-astra-sol)
the Astra and Sol workflow for Codex.

| Role | Agent | Responsibility |
| --- | --- | --- |
| Decision lead | Opus 5.5 Max: the session itself, or the `i2e-opus-lead` subagent | Set the contract and plan, own the architecture and key invariants, and review the work. |
| Implementers | Sonnet 5.5 Max `i2e-sonnet-implementer` subagents | Implement bounded slices with test-first, property, and end-to-end proof; run in parallel only on separate files. |
| Repair takeover | Opus 5.5 Max | After two failed repair rounds, reassess and take over or narrow the slice. |
| Independent review | Fresh Opus 5.5 Max `i2e-opus-lead` | Review consequential changes against the requirements and raw evidence. |

If the same required check still fails after a third repair round, the session stops
that item and brings the evidence to you. At the end, it reports what was proven,
adds what it learned to the shared library as candidates, and merges public-safe findings into the shared catalog at successful handoff.

The workflow is built on engineering practices from
[Addy Osmani's agent-skills](https://github.com/addyosmani/agent-skills). Credit to
Addy Osmani for the foundational engineering skillset; this branch adapts those
practices into a standalone Issue-to-Edit workflow. It is an independent adaptation,
not an official upstream release or endorsement.

## Start on another machine

You need Git, Python 3.10 or later, and Claude Code with subagent support and access
to `claude-opus-5-5` and `claude-sonnet-5-5` at `max` effort.

```sh
git clone --branch i2e-opus-sonnet https://github.com/bowang-solutionstream/i2e-team.git i2e-opus-sonnet
cd i2e-opus-sonnet
python3 scripts/install.py
python3 scripts/install.py --check
```

The installer copies the skill to `skills/i2e-opus-sonnet` and its subagent
definitions to `agents/i2e-opus-sonnet` inside `$CLAUDE_CONFIG_DIR`, or `~/.claude`
when that is unset, so every Claude Code session can use them. It has no third-party
dependency, does not contact the network, and changes no settings. Start a new
Claude Code session afterwards to load the skill and agents.

## The shared property and rule library

All three I2E workflows fetch the latest merged catalog from [main](https://github.com/bowang-solutionstream/i2e-team/tree/main) at intake. After successful delivery, the coordinator publishes public-safe properties and lessons from observed misses to their category branches and merges them into the catalog. A run with no new findings creates no commit. The [library guide](skills/i2e-opus-sonnet/references/library.md) covers the commands, evidence and retry behavior.

## Update

```sh
git pull --ff-only
python3 scripts/install.py --update
python3 scripts/install.py --check
```

Identical installs are no-ops. A different existing installation is refused unless
`--update` is given; each replaced bundle is kept under a timestamped run in
`.i2e-opus-sonnet-backups` inside the Claude config directory, and the installer
prints the backup path. If an installation fails partway, the installer puts back
what it replaced. `--dry-run` previews without writing, and `--check` is read-only.

## Maintain and validate

Edit the sources under `skills/`, not an installed copy. The `scripts/`, `tests/`,
and `library-template/` folders and the skill's `references/library.md` are shared
with the `i2e-fable-opus` branch: make the same change on both branches.

```sh
python3 scripts/validate.py
python3 -m unittest discover -s tests -v
git diff --check
```

The validator checks the skill's structure and metadata, its exact subagents with
their pinned models and effort, the library guide, and local links. On this branch,
the tests cover the library tool and this skill's validation, installation, update,
and rollback. The full installer and validator tests need the pinned guides on the
`i2e-fable-opus` branch and run there. These checks do not establish model quality
or cost savings; see [validation evidence](docs/validation.md). An optional
[GitHub Actions template](docs/github-actions-validate.yml) runs the same checks.

## Credits and license notices

- [Addy Osmani's agent-skills](https://github.com/addyosmani/agent-skills) provides
  the foundational practices. Its MIT license is retained in
  `skills/i2e-opus-sonnet/notices/`.
- [Pattern, Inc.'s code-mint](https://github.com/patterninc/code-mint) contributed
  the issue-refinement guidance; its Apache 2.0 license is retained in the same
  folder.
- The verification practices adapt Addy Osmani's
  [How the Claude Code team thinks about verification](https://claude.dev/blog/how-the-claude-code-team-thinks-about-verification/).

The skill's [NOTICE.md](skills/i2e-opus-sonnet/NOTICE.md) records source revisions
and adaptation details. No repository-wide license is declared for the original
orchestration and tooling, and this adaptation does not relicense them. This branch
continues the `i2e-opus-sonnet` branch of the `bowang-solutionstream/i2e-fable-opus`
repository.

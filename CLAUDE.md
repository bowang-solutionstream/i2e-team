# Package maintenance

This branch of the i2e-team collection holds the `i2e-fable-opus` skill. Its source
of truth is `skills/i2e-fable-opus/`, including its subagent definitions under
`agents/`. The skill must install and run on its own. Keep conditional detail in the
bundled references and load only what the task needs.

Preserve the model and role contract: Fable plans and gives the main code review,
Opus works and proves the change end to end, doubt reviews run only with the user's
approval, and the security audit runs only when a change touches a trust boundary.
Keep the subagents' tool and deny lists, user authority, repository requirements,
and honest completion states.

Do not edit the pinned guides under `skills/i2e-fable-opus/references/lifecycle/`;
to move to another upstream revision, replace the snapshot, its manifest, and the
pinned constants in `scripts/validate.py` together.

`scripts/`, `tests/`, `library-template/`, `.gitignore`,
`docs/github-actions-validate.yml`, and `references/library.md` are shared with the
`i2e-opus-sonnet` branch; make the same change on both branches. Library entries are
user data: they live in the library repository, never in this one. Do not add
credentials, customer examples, machine-specific paths, or private run logs.

Validate with `python3 scripts/validate.py`. For installer, validator, or library
tool changes, also run `python3 -m unittest discover -s tests -v`. Behavioral
scenario runs are separate from these structural checks; do not claim model quality
or cost savings from them.

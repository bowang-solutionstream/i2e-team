# Package maintenance

This branch of the i2e-team collection holds the `i2e-opus-sonnet` skill. Its source
of truth is `skills/i2e-opus-sonnet/`, including its subagent definitions under
`agents/`. The skill must install and run on its own. Keep conditional detail in the
bundled references and load only what the task needs.

Preserve the model and role contract: Opus leads, decides, and reviews, and Sonnet
implements bounded slices. Keep the subagents' pins, user authority, repository
requirements, and honest completion states.

`scripts/`, `tests/`, `library-template/`, `.gitignore`,
`docs/github-actions-validate.yml`, and `references/library.md` are shared with the
`i2e-fable-opus` branch; make the same change on both branches. Library entries are
user data: they live in the library repository, never in this one. Do not add
credentials, customer examples, machine-specific paths, or private run logs.

Validate with `python3 scripts/validate.py`. For installer, validator, or library
tool changes, also run `python3 -m unittest discover -s tests -v` here and on the
`i2e-fable-opus` branch, where the full installer and validator tests run.
Behavioral scenario runs are separate from these structural checks; do not claim
model quality or cost savings from them.

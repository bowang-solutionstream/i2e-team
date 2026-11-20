---
id: rule-run-every-ci-job-before-claiming-the-gate
kind: rule
type: blind-spot
status: candidate
tags: ci, runtime, verification
applies-to: repositories with CI workflows
seen-in: a change adding saved test cases to rules and running them before release (2026-11)
updated: 2026-11-20
---

# Run every CI job, on the pinned runtime, before calling the gate green

## Trigger

A run reports the repository's local check command as its gate while the CI workflow does more: other jobs (a production build, a container start with a health check), or a runtime version pinned in a version file, Dockerfile or workflow that differs from the machine's.

## Check

Read the CI workflow and every runtime pin at intake. Run each job's steps on the final candidate, on the pinned runtime (a container works), or record each one not run as a proof gap with the reason.

## Why it flags

A green local check says nothing about a build step, a container start or another major version of the runtime, and those are what CI and the deployment run.

## Cases

A run proved every change with the local check on the machine's newer Node and never ran CI's build, its Compose job or the pinned Node 22; the main review sent it back for that alone.

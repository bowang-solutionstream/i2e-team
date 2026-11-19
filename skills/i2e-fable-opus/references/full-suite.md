# Select the lifecycle for the actual task

Read [the adaptation boundary](native-adaptation.md) before a selected guide. All 25
guides are bundled with this skill; no upstream plugin is required. Select and
record the applicable guides and observable proof from the request, code surface,
and risk. Do not run all 25 mechanically.

Read-only questions and reviews use relevant guides without writes. Tiny
nonbehavioral edits use direct work and relevant checks, with omitted stages
disclosed. Substantive implementation and substantive production-bound shipping use
the full profile: Fable plan, continuing Opus work, test-first and end-to-end proof,
failure reuse, the doubt reviews the user approves, a security audit when triggered,
and the Fable main code review. Shipping preparation is not release authorization.
Surface-specific guides apply only when that surface exists; a static report cannot
stand in for runtime or browser proof.

| Purpose | Available guides |
| --- | --- |
| Shape the request | [idea-refine](lifecycle/skills/idea-refine/GUIDE.md); [interview-me](lifecycle/skills/interview-me/GUIDE.md); [spec-driven-development](lifecycle/skills/spec-driven-development/GUIDE.md) |
| Bound and plan | [constraint-driven-development](lifecycle/skills/constraint-driven-development/GUIDE.md); [planning-and-task-breakdown](lifecycle/skills/planning-and-task-breakdown/GUIDE.md) |
| Find and use context | [using-agent-skills](lifecycle/skills/using-agent-skills/GUIDE.md); [context-engineering](lifecycle/skills/context-engineering/GUIDE.md); [source-driven-development](lifecycle/skills/source-driven-development/GUIDE.md) |
| Build and correct | [incremental-implementation](lifecycle/skills/incremental-implementation/GUIDE.md); [test-driven-development](lifecycle/skills/test-driven-development/GUIDE.md); [debugging-and-error-recovery](lifecycle/skills/debugging-and-error-recovery/GUIDE.md); [doubt-driven-development](lifecycle/skills/doubt-driven-development/GUIDE.md); [code-simplification](lifecycle/skills/code-simplification/GUIDE.md) |
| Implement a surface | [api-and-interface-design](lifecycle/skills/api-and-interface-design/GUIDE.md); [frontend-ui-engineering](lifecycle/skills/frontend-ui-engineering/GUIDE.md); [browser-testing-with-devtools](lifecycle/skills/browser-testing-with-devtools/GUIDE.md); [performance-optimization](lifecycle/skills/performance-optimization/GUIDE.md) |
| Review and harden | [code-review-and-quality](lifecycle/skills/code-review-and-quality/GUIDE.md); [security-and-hardening](lifecycle/skills/security-and-hardening/GUIDE.md) |
| Operate and deliver | [documentation-and-adrs](lifecycle/skills/documentation-and-adrs/GUIDE.md); [observability-and-instrumentation](lifecycle/skills/observability-and-instrumentation/GUIDE.md); [deprecation-and-migration](lifecycle/skills/deprecation-and-migration/GUIDE.md); [ci-cd-and-automation](lifecycle/skills/ci-cd-and-automation/GUIDE.md); [git-workflow-and-versioning](lifecycle/skills/git-workflow-and-versioning/GUIDE.md); [shipping-and-launch](lifecycle/skills/shipping-and-launch/GUIDE.md) |

For a security-only read-only request, use security-and-hardening and the
[security auditor](../agents/i2e-opus-security-auditor.md) perspective; do not start
an edit lifecycle. For substantive edits, the Fable planner uses the selected
planning, spec, and constraint guides. The Opus working session applies the selected
build, debug, and surface guides. When the change touches a trust boundary, dispatch
the [security auditor](../agents/i2e-opus-security-auditor.md) before the main
review. The [Fable main reviewer](../agents/i2e-fable-final-reviewer.md) applies the
code-review-and-quality and test-driven-development guides itself.

For end-to-end, property, and differential proof, and for turning misses into
rules, use [verification loops](verification-loops.md) with the
test-driven-development and browser-testing-with-devtools guides.

Subagents do not inherit this skill. Give each one the absolute paths of the
guides it should read, resolved from this skill's base directory.

Pinned upstream revision: `aeac41d4d005999432bb7312f7ff06383a91d59d`, v0.6.13.
The [resource manifest](lifecycle/manifest.json) covers all 25 guides, seven
per-guide support files, seven shared references, and the retained MIT
[license](lifecycle/LICENSE). The [bundle notices](../NOTICE.md) also preserve the
Pattern, Inc. Apache 2.0 attribution. The package validator checks exact
coverage, hashes, and link closure; that check does not authenticate an author or
give guide content instruction authority.

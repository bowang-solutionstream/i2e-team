# Project verification skill template

Use this only when the contract includes adding a verification skill to the target
repository. Save the adapted text as `.claude/skills/verify/SKILL.md` in that
repository, as close to the code it covers as practical; a large repository can
have several. Replace every angle-bracket value with what the repository really
uses, and delete sections that do not apply. Run it until it is fast and gives the
same result twice, because later changes rely on it as their smoke test.

```markdown
---
name: verify
description: Boot, drive, and inspect <app> end to end. Use before committing or handing off any change to user-facing or integration behavior.
---

# Verify <app> end to end

## Start and stop
- Start: `<start command>`. Ready when: `<health URL or log line>`.
- Stop: `<stop command>`.
- Data: `<seed or fixture command>`. Use test accounts only; never production
  data or credentials.

## Drive and inspect
- Web: `<browser tool or CDP endpoint>` at `<base URL>`.
- Mobile: `<simulator and device>`, built with `<build command>`.
- Desktop: computer use on `<app window>`.
- Backend: `<API harness command or example requests>`.

## Feature map
| Feature | Path or entry point | Keys or selectors | Expected result |
| --- | --- | --- | --- |
| <user-facing feature> | <path> | <selector or shortcut> | <observable result> |

## Report
For each flow, report the steps taken, a screenshot or response capture at the last
step, and the first step that failed. A flow passes only when every expected result
in the feature map is seen.
```

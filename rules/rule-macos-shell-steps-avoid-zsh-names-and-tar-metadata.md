---
id: rule-macos-shell-steps-avoid-zsh-names-and-tar-metadata
kind: rule
type: instruction
status: candidate
tags: tooling, shell, zsh, macos, archives, containers
applies-to: agent shell steps on macOS
seen-in: a change adding saved test cases to rules and running them before release (2026-11)
updated: 2026-11-20
---

# Shell steps on macOS avoid zsh's special names and macOS archive metadata

## Trigger

A command run in zsh loops with a variable named path (or cdpath, fpath, manpath) or follows a variable with a colon (as in $H:apps/file); or a run copies a macOS working tree into a Linux container or another machine as a tar archive, or bind-mounts a file from a folder the container runtime does not share.

## Check

Use other loop names and write ${var} before a colon; a broken PATH shows as "command not found" for every later tool. Make archives with `COPYFILE_DISABLE=1 tar --no-mac-metadata --no-xattrs`, count their raw entries with a tool that shows AppleDouble files (macOS tar hides them when it lists), and send them on stdin rather than through a bind mount of an unshared folder.

## Why it flags

zsh ties path to PATH, so the loop removes every command, and $H:a applies a modifier that mangles the argument. macOS tar adds a "._name" file for every file with extended attributes, which GNU tar extracts as real files, and an unshared bind-mount source arrives as an empty folder.

## Cases

- A loop named path broke curl, python3 and docker for the rest of a script; a git show argument written $H:apps/... became an absolute file path.
- A container gate failed its contract check on 30 "._*.json" files, one per JSON file, none of them in the project.

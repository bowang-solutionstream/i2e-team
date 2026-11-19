#!/usr/bin/env python3
"""Validate the i2e skill bundles using only the Python standard library."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
from urllib.parse import unquote, urlsplit


FABLE = ("claude-fable-5-2", "max")
OPUS = ("claude-opus-5-5", "max")
SONNET = ("claude-sonnet-5-5", "max")
# Report-only roles may read and search local files, nothing else.
READ_ONLY_TOOLS = frozenset({"Read", "Grep", "Glob"})
REPORT_ONLY_DENIED = frozenset({"Edit", "Write", "NotebookEdit", "Bash", "Agent", "WebFetch", "WebSearch"})
# Only the coordinating session starts subagents.
WORKER_DENIED = frozenset({"Agent"})
# Each skill's Claude Code subagent definitions carry the role's model, effort, and tool
# limits: (model, effort, allowed tools or None to keep the session's tools, required
# denials or None). A skill with "lifecycle" bundles the pinned guide snapshot.
SKILLS = {
    "i2e-fable-opus": {
        "lifecycle": True,
        "agents": {
            "i2e-fable-planner": (*FABLE, READ_ONLY_TOOLS, REPORT_ONLY_DENIED),
            "i2e-fable-final-reviewer": (*FABLE, READ_ONLY_TOOLS, REPORT_ONLY_DENIED),
            "i2e-opus-implementer": (*OPUS, None, WORKER_DENIED),
            "i2e-opus-doubt-reviewer": (*OPUS, READ_ONLY_TOOLS, REPORT_ONLY_DENIED),
            "i2e-opus-security-auditor": (*OPUS, READ_ONLY_TOOLS, REPORT_ONLY_DENIED),
        },
    },
    "i2e-opus-sonnet": {
        "lifecycle": False,
        "agents": {
            "i2e-opus-lead": (*OPUS, None, None),
            "i2e-sonnet-implementer": (*SONNET, None, None),
        },
    },
}
# Every skill bundles the same guide to the shared property and rule library.
SHARED_GUIDE = Path("references") / "library.md"
# The lifecycle guides are a pinned upstream snapshot verified by its manifest.
LIFECYCLE = Path("references") / "lifecycle"
UPSTREAM = {
    "repository": "https://github.com/addyosmani/agent-skills",
    "revision": "aeac41d4d005999432bb7312f7ff06383a91d59d",
    "version": "0.6.13",
    "license": "LICENSE",
}
CAPABILITIES = frozenset({
    "api-and-interface-design", "browser-testing-with-devtools", "ci-cd-and-automation",
    "code-review-and-quality", "code-simplification", "constraint-driven-development",
    "context-engineering", "debugging-and-error-recovery", "deprecation-and-migration",
    "documentation-and-adrs", "doubt-driven-development", "frontend-ui-engineering",
    "git-workflow-and-versioning", "idea-refine", "incremental-implementation", "interview-me",
    "observability-and-instrumentation", "performance-optimization", "planning-and-task-breakdown",
    "security-and-hardening", "shipping-and-launch", "source-driven-development",
    "spec-driven-development", "test-driven-development", "using-agent-skills",
})
SUPPORT = frozenset({
    "skills/constraint-driven-development/references/floor-guard.md",
    "skills/idea-refine/examples.md", "skills/idea-refine/frameworks.md",
    "skills/idea-refine/refinement-criteria.md", "skills/idea-refine/scripts/idea-refine.sh",
    "skills/performance-optimization/references/optimization-patterns.md",
    "skills/security-and-hardening/references/hardening-patterns.md",
    "references/accessibility-checklist.md", "references/definition-of-done.md",
    "references/observability-checklist.md", "references/orchestration-patterns.md",
    "references/performance-checklist.md", "references/security-checklist.md",
    "references/testing-patterns.md", "LICENSE",
})
REPO_ROOT = Path(__file__).resolve().parent.parent


class ValidationError(ValueError):
    """A package or installed tree does not satisfy the package contract."""


def tree_snapshot(directory: Path) -> dict[str, str]:
    """Describe the complete tree, refusing links and non-regular entries."""
    if directory.is_symlink() or not directory.is_dir():
        raise ValidationError(f"Expected a real directory: {directory}")
    result: dict[str, str] = {}
    for entry in sorted(directory.rglob("*")):
        name = entry.relative_to(directory).as_posix()
        if entry.is_symlink():
            raise ValidationError(f"Symlinks are not supported: {entry}")
        if entry.is_dir():
            result[name + "/"] = "directory"
        elif entry.is_file():
            result[name] = hashlib.sha256(entry.read_bytes()).hexdigest()
        else:
            raise ValidationError(f"Unsupported filesystem entry: {entry}")
    return result


def string_mappings(text: str, source: Path) -> dict[str, str]:
    """Read the small string-mapping YAML subset used by skill metadata.

    Supports nested mappings, plain/quoted strings, and |/> block strings.
    This deliberately is not a general-purpose YAML parser.
    """
    values: dict[str, str] = {}
    parents: list[tuple[int, str]] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"( *)([A-Za-z_][A-Za-z0-9_-]*):(?:\s+(.*))?", line)
        if not match:
            raise ValidationError(f"Unsupported metadata syntax in {source}: {line}")
        indent, key, value = len(match[1]), match[2], (match[3] or "").strip()
        while parents and parents[-1][0] >= indent:
            parents.pop()
        full_key = ".".join([parent[1] for parent in parents] + [key])
        if full_key in values:
            raise ValidationError(f"Duplicate metadata key {full_key} in {source}")
        if not value:
            parents.append((indent, key))
            continue
        if value in ("|", "|-", "|+", ">", ">-", ">+"):
            parts = []
            while index < len(lines):
                child = lines[index]
                if child.strip() and len(child) - len(child.lstrip(" ")) <= indent:
                    break
                parts.append(child.strip())
                index += 1
            value = (" " if value.startswith(">") else "\n").join(parts).strip()
        elif value.startswith('"'):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValidationError(f"Invalid quoted string in {source}: {full_key}") from exc
        elif value.startswith("'"):
            if not value.endswith("'") or len(value) < 2:
                raise ValidationError(f"Invalid quoted string in {source}: {full_key}")
            value = value[1:-1].replace("''", "'")
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
            if value.lower() in {"true", "false", "null", "~"} or re.fullmatch(r"[-+]?\d+(?:\.\d+)?", value):
                raise ValidationError(f"Expected a metadata string in {source}: {full_key}")
        values[full_key] = value
    return values


def require_string(values: dict[str, str], key: str, source: Path) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"Missing nonempty string {key} in {source}")
    if value.strip().lower() in {"todo", "tbd", "placeholder", "null", "~"}:
        raise ValidationError(f"Placeholder value for {key} in {source}")
    return value


def markdown_metadata(path: Path, expected_name: str) -> dict[str, str]:
    """Check the frontmatter shared by skills and subagent definitions."""
    text = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", text, re.DOTALL)
    if not match:
        raise ValidationError(f"Missing YAML frontmatter in {path}")
    values = string_mappings(match[1], path)
    if require_string(values, "name", path) != expected_name:
        raise ValidationError(f"Expected name {expected_name} in {path}")
    require_string(values, "description", path)
    if not text[match.end():].strip():
        raise ValidationError(f"Missing instructions in {path}")
    return values


def local_link_targets(text: str) -> list[str]:
    """Extract inline links/images and reference definitions, ignoring code fences."""
    text = re.sub(r"(?ms)^\s*(`{3,}|~{3,}).*?^\s*\1\s*$", "", text)
    inline = re.findall(r"!?\[[^\]\n]*\]\(\s*(<[^>]+>|[^\s)]+)(?:\s+[^)]*)?\)", text)
    references = re.findall(r"(?m)^ {0,3}\[[^\]\n]+\]:\s*(<[^>]+>|\S+)", text)
    return [target.strip("<>") for target in inline + references]


def validate_markdown(bundle: Path, allowed_root: Path) -> None:
    pinned = bundle / LIFECYCLE
    for path in sorted(bundle.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        # The hash-pinned upstream guides may discuss TODO comments in their prose.
        if not path.is_relative_to(pinned) and re.search(r"\b(?:TODO|TBD|FIXME)\b|\[INSERT\b", text):
            raise ValidationError(f"Unfinished scaffold in {path}")
        for target in local_link_targets(text):
            parsed = urlsplit(target)
            if parsed.scheme == "file" or (not parsed.scheme and parsed.path.startswith("/")):
                raise ValidationError(f"Local links must be relative to the bundle in {path}: {target}")
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            destination = (path.parent / unquote(parsed.path)).resolve()
            if not destination.is_relative_to(allowed_root.resolve()):
                raise ValidationError(f"Local link escapes the bundle in {path}: {target}")
            if not destination.exists():
                raise ValidationError(f"Broken local link in {path}: {target}")


def strict_json(path: Path) -> object:
    """Load JSON without duplicate keys or nonfinite numbers."""
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValidationError(f"Duplicate JSON key {key} in {path}")
            result[key] = value
        return result

    def nonfinite(value: str) -> None:
        raise ValidationError(f"Nonfinite JSON number {value} in {path}")

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique,
                          parse_constant=nonfinite)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Invalid JSON in {path}: {exc}") from exc


def exact_fields(value: object, fields: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValidationError(f"{label} must have exactly the fields: {', '.join(sorted(fields))}")
    return value


def snapshot_path(value: object) -> str:
    """Accept only a normalized relative POSIX path inside the snapshot."""
    path = PurePosixPath(value) if isinstance(value, str) else None
    if (path is None or path.is_absolute() or path.as_posix() != value or "\\" in value
            or any(part in (".", "..") for part in path.parts)):
        raise ValidationError(f"Unsafe lifecycle manifest path: {value!r}")
    return value


def validate_lifecycle(main: Path) -> None:
    """Check exact guide coverage, pinned hashes, and support-file references."""
    root = main / LIFECYCLE
    files = {name: digest for name, digest in tree_snapshot(root).items() if not name.endswith("/")}
    manifest = exact_fields(strict_json(root / "manifest.json"),
                            {"schema_version", "upstream", "capabilities", "resources"}, "Lifecycle manifest")
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        raise ValidationError("Unsupported lifecycle manifest schema_version")
    if manifest["upstream"] != UPSTREAM:
        raise ValidationError("Unexpected lifecycle upstream provenance")
    if not isinstance(manifest["capabilities"], list) or not isinstance(manifest["resources"], list):
        raise ValidationError("Lifecycle manifest capabilities and resources must be lists")
    names, guides = [], set()
    for capability in manifest["capabilities"]:
        exact_fields(capability, {"name", "source_path", "bundled_path"}, "Lifecycle capability")
        name = capability["name"]
        if (name not in CAPABILITIES or capability["source_path"] != f"skills/{name}/SKILL.md"
                or capability["bundled_path"] != f"skills/{name}/GUIDE.md"):
            raise ValidationError(f"Unexpected lifecycle capability: {name!r}")
        names.append(name)
        guides.add(capability["bundled_path"])
    if sorted(names) != sorted(CAPABILITIES):
        raise ValidationError(f"The lifecycle manifest must list each of the {len(CAPABILITIES)} guides once")
    declared: set[str] = set()
    for resource in manifest["resources"]:
        exact_fields(resource, {"source_path", "source_sha256", "bundled_path", "sha256"}, "Lifecycle resource")
        path, source = snapshot_path(resource["bundled_path"]), snapshot_path(resource["source_path"])
        if path in declared:
            raise ValidationError(f"Duplicate lifecycle resource: {path}")
        if source != (path.removesuffix("GUIDE.md") + "SKILL.md" if path in guides else path):
            raise ValidationError(f"Lifecycle source mapping mismatch: {path}")
        for key in ("source_sha256", "sha256"):
            if not isinstance(resource[key], str) or not re.fullmatch(r"[0-9a-f]{64}", resource[key]):
                raise ValidationError(f"Invalid lifecycle {key} for {path}")
        if files.get(path) != resource["sha256"]:
            raise ValidationError(f"Missing or modified lifecycle resource: {path}")
        declared.add(path)
    if declared != guides | SUPPORT:
        raise ValidationError("Lifecycle resources must be exactly the guides and their pinned support files")
    unlisted = set(files) - declared - {"manifest.json"}
    if unlisted:
        raise ValidationError("Unlisted lifecycle file: " + ", ".join(sorted(unlisted)))
    # Guides also name support files in code spans, which the link check ignores.
    for path in sorted(name for name in declared if name.endswith(".md")):
        text = (root / path).read_text(encoding="utf-8")
        for target in re.findall(r"`((?:\.\./)+[A-Za-z0-9_./-]+\.(?:md|sh))(?:#[^`]*)?`", text):
            destination = ((root / path).parent / target).resolve()
            if not destination.is_relative_to(main.resolve()) or not destination.is_file():
                raise ValidationError(f"Broken lifecycle reference in {path}: {target}")


def validate_package(root: Path = REPO_ROOT, *, skill_name: str) -> list[Path]:
    spec = SKILLS[skill_name]
    skills = root / "skills"
    if skills.is_symlink():
        raise ValidationError(f"Symlink source directory is not supported: {skills}")
    main = skills / skill_name
    tree_snapshot(main)
    markdown_metadata(main / "SKILL.md", skill_name)
    for name, (model, effort, tools, denied) in spec["agents"].items():
        path = main / "agents" / f"{name}.md"
        if not path.is_file():
            raise ValidationError(f"Missing subagent definition: {path}")
        values = markdown_metadata(path, name)
        # Other fields, such as permissionMode, memory, or mcpServers, could widen access.
        fields = ({"name", "description", "model", "effort"} | ({"tools"} if tools is not None else set())
                  | ({"disallowedTools"} if denied is not None else set()))
        if {key.split(".", 1)[0] for key in values} != fields:
            raise ValidationError(f"Subagent {name} must declare exactly: {', '.join(sorted(fields))}: {path}")
        if (values["model"], values["effort"]) != (model, effort):
            raise ValidationError(f"Subagent {name} must pin model {model} with effort {effort}: {path}")
        if tools is not None:
            declared = {tool.strip() for tool in values["tools"].split(",")}
            if "" in declared or not declared <= tools:
                raise ValidationError(f"Subagent {name} must be report-only, with tools limited to "
                                      f"{', '.join(sorted(tools))}: {path}")
        if denied is not None and not denied <= {tool.strip() for tool in values["disallowedTools"].split(",")}:
            raise ValidationError(f"Subagent {name} must list {', '.join(sorted(denied))} "
                                  f"in disallowedTools: {path}")
    expected = {f"{name}.md" for name in spec["agents"]}
    unexpected = sorted({path.name for path in (main / "agents").iterdir()} - expected)
    if unexpected:
        raise ValidationError("Unexpected entries in the agents directory: " + ", ".join(unexpected))
    for name in ("references", "templates"):
        directory = main / name
        if not directory.is_dir() or not any(path.is_file() for path in directory.rglob("*")):
            raise ValidationError(f"Missing or empty required directory: {directory}")
    if not (main / SHARED_GUIDE).is_file():
        raise ValidationError(f"Missing shared library guide: {main / SHARED_GUIDE}")
    if spec["lifecycle"]:
        validate_lifecycle(main)
    validate_markdown(main, main)
    return [main]


def selected_skills(root: Path, names: list[str] | None = None) -> list[str]:
    """Return the requested skills, or every known skill present under skills/."""
    skills = root / "skills"
    if skills.is_symlink():
        raise ValidationError(f"Symlink source directory is not supported: {skills}")
    present = sorted(path.name for path in skills.iterdir()
                     if path.is_dir() and not path.name.startswith(".")) if skills.is_dir() else []
    unknown = [name for name in present if name not in SKILLS]
    if unknown:
        raise ValidationError("Unknown skill directory: " + ", ".join(unknown))
    chosen = list(dict.fromkeys(names)) if names else [name for name in SKILLS if name in present]
    if not chosen:
        raise ValidationError(f"No skill bundle found under {skills}")
    return chosen


def validate_suite(root: Path = REPO_ROOT, names: list[str] | None = None) -> list[Path]:
    bundles = [bundle for name in selected_skills(root, names)
               for bundle in validate_package(root, skill_name=name)]
    if len({(bundle / SHARED_GUIDE).read_bytes() for bundle in bundles}) > 1:
        raise ValidationError(f"The shared library guide {SHARED_GUIDE} differs between skills")
    template = root / "library-template"
    if template.is_dir():
        tree_snapshot(template)
        validate_markdown(template, template)
    return bundles


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="Package repository root")
    parser.add_argument("--skill", action="append", choices=sorted(SKILLS),
                        help="Skill to validate; repeat for more (default: every skill present)")
    args = parser.parse_args()
    try:
        bundles = validate_suite(args.root, args.skill)
    except (ValidationError, OSError, UnicodeError) as exc:
        print(f"Validation failed: {exc}", file=sys.stderr)
        return 1
    print("Validated: " + ", ".join(bundle.name for bundle in bundles))
    print("Structural checks passed; this does not evaluate model behavior.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

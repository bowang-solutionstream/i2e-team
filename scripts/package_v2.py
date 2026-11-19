#!/usr/bin/env python3
"""Stage and verify the exact local v8 skill payload."""

import argparse
from contextlib import contextmanager
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import posixpath
import re
import stat
import sys
import tarfile
from urllib.parse import unquote, urlsplit
import zlib


SKILL = "i2e-astra-sol"
PREVIOUS_SKILL = "i2e-team"
SCHEMA = "i2e-team-package-v2"
STATUS = "STAGED_NOT_INSTALLED"
ARCHIVE_SKILLS = {f"{name}.tar.gz": name for name in (SKILL, PREVIOUS_SKILL)}
MANIFEST = "manifest.json"
DEPENDENCIES = {"canonical_case_helper": {
    "entrypoint": "shared_cases.py", "required": True, "bundled": False,
}}
DIRECTORIES = {
    "agents": {"openai.yaml", "i2e_team_sol.toml", "i2e_team_astra.toml"},
    "scripts": {"i2e.py", "v2_contract.py", "v2_runtime.py", "worker_adapter.py", "github_adapter.py",
                "verify_labels.py", "critical_flow.py", "critical_issues.py", "critical_routing.py", "critical_speckit.py",
                "fetch_library.py", "records.py"},
    "references": {
        "runtime.md", "runtime-v1.md", "settings.md", "teaching.md", "records-v2.md",
        "policy.md", "execution.md", "verification.md", "delivery.md", "adoption.md", "label-verification.json",
        "critical-four-rounds.md",
    },
    "prompts": {"plan-review.md", "implementation.md", "verification.md"},
}
FILES = {"SKILL.md"} | {f"{directory}/{name}" for directory, names in DIRECTORIES.items() for name in names}
PRESET_FILES = {"agents/i2e_team_sol.toml", "agents/i2e_team_astra.toml"}
INTAKE_SCRIPTS = {"fetch_library.py", "records.py"}
PRE_INTAKE_FILES = FILES - {f"scripts/{name}" for name in INTAKE_SCRIPTS}
PREVIOUS_FILES = PRE_INTAKE_FILES - {"scripts/critical_flow.py", "scripts/critical_issues.py", "scripts/critical_routing.py",
                          "scripts/critical_speckit.py", "references/critical-four-rounds.md"}
MAX_PAYLOAD = 16 * 1024 * 1024
MAX_ARCHIVE = MAX_PAYLOAD + 1024 * 1024
MAX_MANIFEST = 64 * 1024
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
LINKS = (
    re.compile(r"\]\(\s*(?:<([^>\n]+)>|([^\s)]+))"),
    re.compile(r"(?m)^[ \t]{0,3}\[[^\]\n]+\]:[ \t]*(?:<([^>\n]+)>|([^\s]+))"),
)


def sha256(body):
    return hashlib.sha256(body).hexdigest()


def canonical_path(value):
    path = Path(value).absolute()
    if ".." in path.parts or path.anchor != "/":
        raise ValueError(f"Use a canonical absolute or relative path: {value}")
    if sys.platform == "darwin" and path.parts[:2] == ("/", "var") and Path("/var").is_symlink():
        if os.readlink("/var") not in {"private/var", "/private/var"}:
            raise ValueError("Unsupported macOS /var alias")
        return Path("/private/var", *path.parts[2:])
    return path


@contextmanager
def open_directory(path):
    fd = os.open("/", DIR_FLAGS)
    try:
        for part in path.parts[1:]:
            parent = fd
            fd = os.open(part, DIR_FLAGS, dir_fd=parent)
            os.close(parent)
        yield fd
    finally:
        os.close(fd)


@contextmanager
def child_directory(parent, name, *, create=False):
    if create:
        os.mkdir(name, mode=0o700, dir_fd=parent)
    fd = os.open(name, DIR_FLAGS, dir_fd=parent)
    try:
        if create:
            info = os.fstat(fd)
            if info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise ValueError(f"New output directory is not private: {name}")
        yield fd
    finally:
        os.close(fd)


def exact_entries(directory, names):
    observed = set(os.listdir(directory))
    if observed != names:
        raise ValueError(f"Unexpected inventory. Missing {sorted(names - observed)}. Extra {sorted(observed - names)}.")


def file_identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_file(directory, name, limit):
    entry = os.stat(name, dir_fd=directory, follow_symlinks=False)
    if not stat.S_ISREG(entry.st_mode) or entry.st_nlink != 1 or entry.st_size > limit:
        raise ValueError(f"Expected a bounded, single-link regular file: {name}")
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(fd)
        if file_identity(entry) != file_identity(before):
            raise ValueError(f"File changed before opening: {name}")
        body = stream.read(limit + 1)
        after = os.fstat(fd)
        visible = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if len(body) != before.st_size or file_identity(before) != file_identity(after) or (
            file_identity(after) != file_identity(visible)
        ):
            raise ValueError(f"File changed while reading: {name}")
    return body


def write_file(directory, name, body):
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    with os.fdopen(fd, "wb") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(fd)


def read_skill(directory, directories=DIRECTORIES):
    root_entries = {"SKILL.md", *directories}
    exact_entries(directory, root_entries)
    payload = {"SKILL.md": read_file(directory, "SKILL.md", MAX_PAYLOAD)}
    remaining = MAX_PAYLOAD - len(payload["SKILL.md"])
    for folder, names in sorted(directories.items()):
        with child_directory(directory, folder) as child:
            exact_entries(child, names)
            for name in sorted(names):
                body = read_file(child, name, remaining)
                payload[f"{folder}/{name}"] = body
                remaining -= len(body)
            exact_entries(child, names)
    exact_entries(directory, root_entries)
    return payload


def check_local_links(payload):
    for name, body in payload.items():
        if not name.endswith(".md"):
            continue
        document = body.decode("utf-8")
        for pattern in LINKS:
            for match in pattern.finditer(document):
                target = match[1] or match[2]
                url = urlsplit(target)
                if url.scheme and url.scheme != "file":
                    continue
                if not url.path and not url.netloc and not url.scheme:
                    continue
                local = unquote(url.path, errors="strict")
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), local))
                if url.scheme or url.netloc or local.startswith("/") or "\\" in local or resolved not in payload:
                    raise ValueError(f"Broken or out-of-package local link in {name}: {target}")


def tar_dirs(skill):
    return {skill} | {f"{skill}/{directory}" for directory in DIRECTORIES}


def tar_bytes(payload, skill=SKILL):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:", format=tarfile.USTAR_FORMAT) as archive:
        for name in sorted(tar_dirs(skill)):
            member = tarfile.TarInfo(name)
            member.type = tarfile.DIRTYPE
            member.mode = 0o755
            archive.addfile(member)
        for name, body in sorted(payload.items()):
            member = tarfile.TarInfo(f"{skill}/{name}")
            member.mode = 0o644
            member.size = len(body)
            archive.addfile(member, io.BytesIO(body))
    return stream.getvalue()


def fingerprint(body):
    return {"sha256": sha256(body), "size": len(body)}


def manifest_for(payload, archive, skill=SKILL):
    return {"schema": SCHEMA, "status": STATUS, "files": {name: fingerprint(body) for name, body in payload.items()},
            "archive": {"path": f"{skill}.tar.gz", **fingerprint(archive)}, "external_dependencies": DEPENDENCIES}


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate manifest field: {key}")
        result[key] = value
    return result


def check_fingerprint(row, limit, fields):
    if not isinstance(row, dict) or row.keys() != fields:
        raise ValueError("Invalid manifest fingerprint fields")
    if type(row["size"]) is not int or not 0 <= row["size"] <= limit or not isinstance(row["sha256"], str) or (
        not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
    ):
        raise ValueError("Invalid manifest size or SHA-256")


def read_manifest(body):
    manifest = json.loads(body.decode("utf-8"), object_pairs_hook=unique_fields)
    fields = {"schema", "status", "files", "archive", "external_dependencies"}
    if not isinstance(manifest, dict) or manifest.keys() != fields or (
        manifest["schema"] != SCHEMA or manifest["status"] != STATUS
    ):
        raise ValueError("Invalid package manifest schema or stage status")
    if json.dumps(manifest["external_dependencies"], sort_keys=True) != json.dumps(DEPENDENCIES, sort_keys=True):
        raise ValueError("Invalid external canonical-case-helper dependency")
    files = manifest["files"]
    if not isinstance(files, dict) or files.keys() not in (FILES, PRE_INTAKE_FILES, PREVIOUS_FILES, PREVIOUS_FILES - PRESET_FILES):
        raise ValueError("Invalid package manifest inventory")
    for row in files.values():
        check_fingerprint(row, MAX_PAYLOAD, {"size", "sha256"})
    if sum(row["size"] for row in files.values()) > MAX_PAYLOAD:
        raise ValueError("Manifest payload exceeds the package limit")
    check_fingerprint(manifest["archive"], MAX_ARCHIVE, {"path", "size", "sha256"})
    archive_name = manifest["archive"]["path"]
    if not isinstance(archive_name, str) or archive_name not in ARCHIVE_SKILLS:
        raise ValueError("Invalid archive path")
    return manifest


def read_archive(compressed, manifest):
    archive_name = manifest["archive"]["path"]
    skill = ARCHIVE_SKILLS[archive_name]
    if {"path": archive_name, **fingerprint(compressed)} != manifest["archive"]:
        raise ValueError("Archive size or SHA-256 differs from the manifest")
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    raw = decompressor.decompress(compressed, MAX_ARCHIVE + 1)
    if len(raw) > MAX_ARCHIVE or not decompressor.eof or decompressor.unconsumed_tail or decompressor.unused_data:
        raise ValueError("Archive must be one bounded, complete gzip member")
    payload, directories = {}, set()
    prefix = f"{skill}/"
    allowed_dirs = tar_dirs(skill)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        for member in archive:
            if member.type == tarfile.DIRTYPE and member.name in allowed_dirs and member.name not in directories:
                directories.add(member.name)
                continue
            name = member.name.removeprefix(prefix)
            if member.type != tarfile.REGTYPE or not member.name.startswith(prefix) or name not in manifest["files"] or name in payload:
                raise ValueError(f"Unsafe or duplicate archive member: {member.name}")
            expected = manifest["files"][name]
            if member.size != expected["size"]:
                raise ValueError(f"Unexpected archive member size: {name}")
            with archive.extractfile(member) as stream:
                body = stream.read(member.size + 1)
            if fingerprint(body) != expected:
                raise ValueError(f"Unexpected archive member bytes: {name}")
            payload[name] = body
    if payload.keys() != manifest["files"].keys() or directories != allowed_dirs or tar_bytes(payload, skill) != raw:
        raise ValueError("Archive member inventory or USTAR encoding is invalid")
    check_local_links(payload)
    return payload


def require_separate(source, destination):
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("Source and output must use separate paths")


def stage(source, destination):
    require_separate(source, destination)
    with open_directory(source) as directory:
        directories = DIRECTORIES
        with child_directory(directory, "scripts") as scripts:
            if INTAKE_SCRIPTS.isdisjoint(os.listdir(scripts)):
                directories = {**DIRECTORIES, "scripts": DIRECTORIES["scripts"] - INTAKE_SCRIPTS}
        payload = read_skill(directory, directories)
    check_local_links(payload)
    # A pinned checkout can still stage its original, pre-rename skill.
    frontmatter = payload["SKILL.md"].decode("utf-8").splitlines()
    skill = SKILL
    if frontmatter[:1] == ["---"] and "---" in frontmatter[1:]:
        header = frontmatter[1:frontmatter.index("---", 1)]
        if f"name: {PREVIOUS_SKILL}" in header:
            skill = PREVIOUS_SKILL
    archive_name = f"{skill}.tar.gz"
    archive = gzip.compress(tar_bytes(payload, skill), compresslevel=9, mtime=0)
    manifest = (json.dumps(manifest_for(payload, archive, skill), indent=2, sort_keys=True) + "\n").encode("utf-8")
    with open_directory(destination.parent) as parent, child_directory(parent, destination.name, create=True) as output:
        write_file(output, MANIFEST, manifest)
        write_file(output, archive_name, archive)
        exact_entries(output, {MANIFEST, archive_name})
        if read_file(output, MANIFEST, MAX_MANIFEST) != manifest or read_file(output, archive_name, MAX_ARCHIVE) != archive:
            raise ValueError("Staged bytes changed during readback")
    return {"package": str(destination), "manifest": str(destination / MANIFEST), "files": len(payload)}


def verify(package, extraction):
    require_separate(package, extraction)
    with open_directory(package) as directory:
        manifest = read_manifest(read_file(directory, MANIFEST, MAX_MANIFEST))
        archive_name = manifest["archive"]["path"]
        exact_entries(directory, {MANIFEST, archive_name})
        compressed = read_file(directory, archive_name, MAX_ARCHIVE)
    payload = read_archive(compressed, manifest)
    skill_name = ARCHIVE_SKILLS[archive_name]
    directories = {
        folder: {name for name in names if f"{folder}/{name}" in payload}
        for folder, names in DIRECTORIES.items()
    }
    with open_directory(extraction.parent) as parent, child_directory(parent, extraction.name, create=True) as output:
        with child_directory(output, skill_name, create=True) as skill:
            write_file(skill, "SKILL.md", payload["SKILL.md"])
            for folder, names in sorted(directories.items()):
                with child_directory(skill, folder, create=True) as child:
                    for name in sorted(names):
                        write_file(child, name, payload[f"{folder}/{name}"])
            if read_skill(skill, directories) != payload:
                raise ValueError("Extracted bytes changed during readback")
        exact_entries(output, {skill_name})
    return {"package": str(package), "extraction": str(extraction), "files": len(payload)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("stage", help="write a fresh private archive and manifest")
    create.add_argument("--source", required=True)
    create.add_argument("--dest", required=True)
    read = commands.add_parser("verify", help="validate before extracting into a fresh private directory")
    read.add_argument("--package", required=True)
    read.add_argument("--extract", required=True)
    args = parser.parse_args()
    try:
        if args.command == "stage":
            result = stage(canonical_path(args.source), canonical_path(args.dest))
        else:
            result = verify(canonical_path(args.package), canonical_path(args.extract))
    except (OSError, ValueError, EOFError, RecursionError, tarfile.TarError, zlib.error) as error:
        print(json.dumps({"state": "BLOCK", "errors": [str(error)]}, sort_keys=True))
        return 1
    print(json.dumps({"state": "PASS", "status": STATUS, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

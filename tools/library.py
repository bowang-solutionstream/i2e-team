"""Read canonical I2E lessons and publish a successful run's public-safe reflection."""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from delivery import WORKFLOWS, accepted
from records import draft_entries, read_catalog, reconcile

REMOTE = "https://github.com/bowang-solutionstream/i2e-team.git"
BRANCH = {"properties": "i2e-property-libraries", "rules": "i2e-misses-to-rules"}
REFS = ("main", *BRANCH.values())
ROOT = Path(__file__).resolve().parents[1]


class Pending(Exception):
    """The reflection needs a retry or a maintainer's reconciliation."""


def git(repo, *args, data=None, index=None, check=True):
    env = os.environ.copy()
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
                "GIT_ALTERNATE_OBJECT_DIRECTORIES"):
        env.pop(key, None)
    if index:
        env["GIT_INDEX_FILE"] = str(index)
    # A public record commit must not expose a contributor's private Git identity.
    for role in ("AUTHOR", "COMMITTER"):
        env[f"GIT_{role}_NAME"] = "I2E Library"
        env[f"GIT_{role}_EMAIL"] = "i2e-library@users.noreply.github.com"
    result = subprocess.run(["git", "-c", "push.followTags=false",
                             "-C", str(repo), *args], input=data, capture_output=True, env=env, check=False)
    if check and result.returncode:
        raise Pending(f"git {args[0]} failed. Check connectivity, access and the library branch history.")
    return result


def oid(repo, *args, **kwargs):
    return git(repo, *args, **kwargs).stdout.decode("ascii").strip()


def catalog(repo, revision):
    return read_catalog(revision, lambda *args: git(repo, *args).stdout)


def fetch(repo):
    refs = [f"+refs/heads/{b}:refs/remotes/library/{b}" for b in REFS]
    git(repo, "fetch", "--no-tags", "--quiet", REMOTE, *refs)
    return {b: oid(repo, "rev-parse", f"refs/remotes/library/{b}") for b in REFS}


def ancestor(repo, older, newer):
    return git(repo, "merge-base", "--is-ancestor", older, newer, check=False).returncode == 0


def commit_entries(repo, index, base, entries, message, other_parent=None):
    git(repo, "read-tree", base, index=index)
    for name, raw in sorted(entries.items()):
        blob = oid(repo, "hash-object", "-w", "--stdin", data=raw)
        git(repo, "update-index", "--add", "--cacheinfo", f"100644,{blob},{name}", index=index)
    tree = oid(repo, "write-tree", index=index)
    parents = ["-p", base]
    if other_parent:
        parents.extend(["-p", other_parent])
    return oid(repo, "commit-tree", tree, *parents, "-m", message)


def publish(args, drafts):
    with tempfile.TemporaryDirectory(prefix="i2e-reflect-") as temp:
        repo = Path(temp) / "git"
        git(temp, "init", "--bare", "--quiet", str(repo))
        for attempt in range(3):
            heads = fetch(repo)
            main = heads["main"]
            changes = reconcile(catalog(repo, main), drafts)
            if not changes:
                return {"status": "NO_CHANGES", "main": main}
            updates = {}
            for folder, branch in BRANCH.items():
                records = {name: raw for name, raw in changes.items() if name.startswith(folder + "/")}
                if not records:
                    continue
                if not ancestor(repo, heads[branch], heads["main"]):
                    raise Pending(f"{branch} contains unmerged work. Reconcile it on main before retrying.")
                topic = commit_entries(repo, Path(temp) / "index", heads[branch], records,
                                       f"Record I2E {folder} from verified delivery")
                main = commit_entries(repo, Path(temp) / "index", main, records,
                                      f"Merge {branch} into main", other_parent=topic)
                updates[branch] = topic
            updates["main"] = main
            accepted(args)
            push = git(repo, "push", "--atomic", REMOTE, *(f"{sha}:refs/heads/{b}" for b, sha in updates.items()),
                       check=False)
            # Also read back an ambiguous push result (for example a disconnected response).
            latest = fetch(repo)
            if all(ancestor(repo, sha, latest[b]) for b, sha in updates.items()):
                return {"status": "MERGED", "main": latest["main"], "merges_at": main,
                        "branches": sorted(set(updates) - {"main"}), "entries": sorted(changes)}
            if push.returncode and latest == heads and attempt == 2:
                raise Pending("Git refused the atomic update. Check write access and branch protections, then retry.")
        raise Pending("Other writers moved the library repeatedly. Keep the drafts and retry.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    listing = actions.add_parser("catalog", help="List validated entries at the pinned local HEAD")
    listing.add_argument("--status", choices=("adopted", "candidate", "retired"))
    reflect = actions.add_parser("reflect", help="Publish completed delivery lessons to the two category branches")
    reflect.add_argument("--workflow", choices=WORKFLOWS, required=True)
    reflect.add_argument("--entries", type=Path, required=True)
    for name in ("i2e", "state", "db", "handoff"):
        reflect.add_argument("--" + name, type=Path)
    reflect.add_argument("--run")
    args = parser.parse_args(argv)
    try:
        if args.action == "catalog":
            head = oid(ROOT, "rev-parse", "HEAD")
            entries = catalog(ROOT, head)
            result = {"revision": head, "entries": [dict(e.fields, path=n) for n, e in sorted(entries.items())
                                                    if args.status in (None, e.fields["status"])]}
        else:
            accepted(args)
            drafts = draft_entries(args.entries)
            result = publish(args, drafts) if drafts else {"status": "NO_CHANGES"}
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError, Pending) as exc:
        print(json.dumps({"status": "PENDING" if isinstance(exc, Pending) else "BLOCKED", "reason": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())

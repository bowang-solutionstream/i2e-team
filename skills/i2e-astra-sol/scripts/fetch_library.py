"""Fetch and validate the current I2E catalog before an invocation starts work."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from time import gmtime, strftime

from records import KINDS, read_catalog

REMOTE = "https://github.com/bowang-solutionstream/i2e-team.git"


def fetch_library(run):
    run.mkdir(parents=True, exist_ok=True, mode=0o700)
    intake = Path(tempfile.mkdtemp(dir=run.resolve(), prefix="i2e-intake-"))
    library = intake / "library"
    env = os.environ.copy()
    # A product repository's Git environment must not redirect the private checkout.
    for key in ("GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
                "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES"):
        env.pop(key, None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        subprocess.run(["git", "clone", "--quiet", "--no-tags", "--depth", "1", "--single-branch",
                        "--branch", "main", REMOTE, str(library)], env=env, check=True)
        def git_output(*args):
            return subprocess.check_output(["git", "-C", str(library), *args], env=env)

        head = git_output("rev-parse", "HEAD").decode("ascii").strip()
        for category in KINDS:
            directory = library / category
            if directory.is_symlink() or not directory.is_dir():
                raise ValueError(f"missing catalog directory: {category}")
        entries = read_catalog(head, git_output)
        receipt = {
            "source": REMOTE, "branch": "main", "revision": head,
            "fetched_at": strftime("%Y-%m-%dT%H:%M:%SZ", gmtime()),
            "entries": [dict(entry.fields, path=name) for name, entry in sorted(entries.items())],
        }
        (intake / "catalog.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        return intake
    except BaseException:
        shutil.rmtree(intake)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path, help="Private run directory outside the product checkout")
    args = parser.parse_args()
    try:
        print(fetch_library(args.run))
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"I2E library intake BLOCKED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

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
        head = subprocess.check_output(["git", "-C", str(library), "rev-parse", "HEAD"], env=env, text=True).strip()
        for category in ("properties", "rules"):
            if not (library / category).is_dir() or (library / category).is_symlink():
                raise ValueError(f"missing catalog directory: {category}")
        checked = subprocess.run([sys.executable, "-B", str(library / "tools/library.py"), "catalog"],
                                 cwd=library, env=env, stdout=subprocess.PIPE, check=False)
        catalog = json.loads(checked.stdout)
        if checked.returncode and isinstance(catalog, dict):
            raise ValueError(catalog.get("reason", "catalog validation failed"))
        if not isinstance(catalog, dict) or catalog.get("revision") != head or not isinstance(catalog.get("entries"), list):
            raise ValueError("catalog validation did not return the fetched revision and entries")
        receipt = dict(catalog, source=REMOTE, branch="main", fetched_at=strftime("%Y-%m-%dT%H:%M:%SZ", gmtime()))
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

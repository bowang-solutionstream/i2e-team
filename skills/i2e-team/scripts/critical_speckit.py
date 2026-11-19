"""Prepare an isolated Codex Spec Kit workspace for a Critical planner."""
import argparse
import fcntl
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


VERSION = "1.4.3"
SOURCE = "git+https://github.com/github/spec-kit.git@980b3d027f4bd7958c35f97f618d854b41320e3f"
SKILLS = ("speckit-specify", "speckit-plan", "speckit-tasks")


def planner_argv(workspace):
    """Run from this private feature workspace with shell networking and connected apps disabled."""
    return [
        "codex", "exec", "--cd", str(workspace), "--skip-git-repo-check", "--model", "gpt-6.2-astra",
        "-c", 'model_reasoning_effort="max"', "-c", 'service_tier="default"',
        "--ignore-user-config", "--ignore-rules", "--disable", "apps", "--disable", "plugins",
        "--disable", "computer_use", "--disable", "multi_agent", "--disable", "multi_agent_v2",
        "--sandbox", "workspace-write", "-c", 'approval_policy="never"',
        "-c", "sandbox_workspace_write.network_access=false", "-c", 'web_search="disabled"', "--json", "-",
    ]


def ready(workspace):
    options = json.loads((workspace / ".specify/init-options.json").read_text())
    if options.get("integration") != "codex" or options.get("speckit_version") != VERSION:
        raise ValueError(f"expected a Codex Spec Kit {VERSION} workspace at {workspace}")
    for name in SKILLS:
        entry = workspace / ".agents/skills" / name / "SKILL.md"
        if not entry.is_file() or not entry.stat().st_size:
            raise ValueError(f"missing Spec Kit planning skill {name}")
    if (workspace / ".agents/skills/speckit-github-taskstoissues").exists() or (
        workspace / ".specify/extensions/github"
    ).exists():
        raise ValueError("select a fresh local planning workspace without the GitHub extension")
    return {"state": "READY", "workspace": str(workspace), "version": VERSION, "skills": list(SKILLS),
            "planner_argv": planner_argv(workspace)}


def prepare(workspace):
    workspace = workspace.expanduser().absolute()
    if workspace.exists():
        return ready(workspace)
    workspace.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (workspace.parent / ".i2e-speckit-setup.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if workspace.exists():
            return ready(workspace)
        cli = shutil.which("specify")
        command = [cli] if cli else []
        if command:
            version = subprocess.run([*command, "version", "--json"], capture_output=True, text=True)
            try:
                matches = version.returncode == 0 and json.loads(version.stdout).get("cli_version") == VERSION
            except (ValueError, AttributeError):
                matches = False
            if not matches:
                command = []
        if not command:
            uv = shutil.which("uv")
            if not uv:
                raise ValueError(f"install Spec Kit {VERSION} or uv to initialize this workspace")
            command = [uv, "tool", "run", "--from", SOURCE, "specify"]
        with tempfile.TemporaryDirectory(prefix=".i2e-speckit-", dir=workspace.parent) as temporary:
            result = subprocess.run(
                [*command, "init", "planning", "--integration", "codex", "--integration-options=--events false",
                 "--script", "sh", "--non-interactive"],
                cwd=temporary, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            if result.returncode:
                raise ValueError(f"Spec Kit initialization failed: {result.stdout[-1800:]}")
            staged = Path(temporary) / "planning"
            ready(staged)
            staged.chmod(0o700)
            staged.rename(workspace)
    return ready(workspace)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path,
                        default=Path.home() / ".local/share/i2e-team/speckit")
    args = parser.parse_args(argv)
    try:
        result = prepare(args.workspace)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"state": "BLOCK", "error": str(error)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

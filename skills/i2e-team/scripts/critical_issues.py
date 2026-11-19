"""Keep a feature's Spec Kit tasks and their development status inside one Critical run."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile


TASK = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+(T[0-9]{3,})\s+(.+?)\s*$")
REF = re.compile(r"issues/([a-f0-9]{64})\.json#(T[0-9]{3,})")
STATES = ("OPEN", "IN_PROGRESS", "DONE")


def parse_tasks(path):
    tasks = {}
    current = None
    fence = None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            if fence is None or stripped[:3] == fence:
                fence = None if fence else stripped[:3]
            current = None
        elif fence is None:
            match = TASK.fullmatch(line)
            if match:
                checked, key, title = match.groups()
                if key in tasks:
                    raise ValueError(f"duplicate Spec Kit task {key}")
                current = {"id": key, "title": title, "details": [],
                           "initial_status": "DONE" if checked.lower() == "x" else "OPEN"}
                tasks[key] = current
            elif stripped and line[:1].isspace() and current is not None:
                current["details"].append(stripped)
            elif stripped:
                current = None
    if not tasks:
        raise ValueError("tasks.md must contain Spec Kit task checkboxes with IDs")
    return tasks


def content(data):
    return (json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as staged:
        temporary = Path(staged.name)
        try:
            staged.write(data)
            staged.flush()
            os.fsync(staged.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def sync_tasks(tasks_path, store_directory):
    """Snapshot the issue definitions. Serialize all board operations with the run lock."""
    tasks = parse_tasks(tasks_path)
    directory = Path(store_directory) / "issues"
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    data = content({"schema": 1, "tasks": list(tasks.values())})
    filename = f"{digest(data)}.json"
    path = directory / filename
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("local issue definitions differ from the accepted snapshot")
    else:
        save(path, data)
    return [{"task": key, "ref": f"issues/{filename}#{key}"} for key in tasks]


def task_board(rows, store_directory, task=None, status=None):
    """Read or update local progress. Reopen changed definitions when Astra revises a plan."""
    root = Path(store_directory)
    if not rows:
        raise ValueError("the current plan has no local issues")
    first = REF.fullmatch(rows[0]["ref"])
    if first is None:
        raise ValueError("invalid local issue reference")
    version = first.group(1)
    data = (root / "issues" / f"{version}.json").read_bytes()
    if digest(data) != version:
        raise ValueError("local issue definitions differ from the accepted snapshot")
    definitions = json.loads(data)["tasks"]
    expected = [{"task": item["id"], "ref": f"issues/{version}.json#{item['id']}"} for item in definitions]
    if expected != rows:
        raise ValueError("local issue references differ from the current plan")
    path = root / "issues" / "progress.json"
    progress = json.loads(path.read_bytes()) if path.exists() else {}
    if task is not None:
        selected = next((item for item in definitions if item["id"] == task), None)
        if selected is None or status not in STATES:
            raise ValueError("select a current task and an OPEN, IN_PROGRESS or DONE status")
        progress[task] = {"definition": digest(content(selected)), "status": status}
        save(path, content(progress))
    board = []
    for item in definitions:
        record = progress.get(item["id"], {})
        current = record["status"] if record.get("definition") == digest(content(item)) else item["initial_status"]
        board.append({"id": item["id"], "title": item["title"], "details": item["details"], "status": current})
    return board

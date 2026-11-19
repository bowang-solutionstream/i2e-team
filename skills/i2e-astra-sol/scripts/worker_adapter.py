"""Read-only proof execution and isolated synthetic macOS worker generations."""
from __future__ import annotations

import contextlib
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import select
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time


MODE = "macos-sandbox-full-clone-v1"
SANDBOX = Path("/usr/bin/sandbox-exec")
_PROFILE = (
    "(version 1) (deny default) "
    "(allow process-exec process-fork file-read* sysctl-read) "
    "(deny file-link) (allow file-write* (subpath {}))"
)
_PROBE = """import pathlib, subprocess, sys
scratch, protected = map(pathlib.Path, sys.argv[1:])
def denied(path):
    try:
        path.write_text("unexpected write")
    except PermissionError:
        return
    raise SystemExit("protected write was allowed")
(scratch / "own").write_text("scratch is writable")
denied(protected)
denied(scratch / "alias")
child = "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('unexpected child write')"
result = subprocess.run([sys.executable, "-B", "-c", child, str(protected)],
                        input=b"", capture_output=True, close_fds=True, check=False)
if result.returncode == 0 or b"PermissionError" not in result.stderr:
    raise SystemExit("protected child write was not denied")
print("qualified read-only")
"""


@lru_cache(maxsize=32)
def _hash_executable(path, identity):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def executable(path):
    target = Path(path)
    if not target.is_absolute() or target != target.resolve(strict=True):
        raise ValueError("proof executable must use an absolute canonical path")
    info = target.stat()
    if not stat.S_ISREG(info.st_mode) or not os.access(target, os.X_OK):
        raise ValueError("proof executable must be an executable regular file")
    identity = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    return {"path": str(target), "sha256": _hash_executable(str(target), identity)}


def _profile(scratch):
    return _PROFILE.format(json.dumps(str(scratch), ensure_ascii=False))


def identity(scratch):
    if sys.platform != "darwin":
        raise ValueError("read-only proof executor is unqualified on this host")
    kernel = os.uname()
    return {"mode": MODE, "tool": executable(SANDBOX), "scratch": str(scratch),
            "host": {"system": kernel.sysname, "release": kernel.release,
                     "version": kernel.version, "machine": kernel.machine},
            "profile_sha256": hashlib.sha256(_profile(scratch).encode()).hexdigest(),
            "probe_sha256": hashlib.sha256(_PROBE.encode()).hexdigest()}


def _execute(scratch, repo, argv, timeout):
    env = {"PATH": os.defpath, "LANG": "C.UTF-8", "TMPDIR": str(scratch),
           "PYTHONDONTWRITEBYTECODE": "1", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_OPTIONAL_LOCKS": "0",
           "GIT_TERMINAL_PROMPT": "0"}
    wrapper = [str(SANDBOX), "-p", _profile(scratch), *argv]
    try:
        result = subprocess.run(wrapper, cwd=repo, env=env, stdin=subprocess.DEVNULL,
                                capture_output=True, close_fds=True, timeout=timeout, check=False)
        return {"argv": wrapper, "exit": result.returncode, "stdout": result.stdout,
                "stderr": result.stderr, "timed_out": False, "launch_error": None}
    except subprocess.TimeoutExpired as exc:
        return {"argv": wrapper, "exit": None, "stdout": exc.stdout or b"",
                "stderr": exc.stderr or b"", "timed_out": True, "launch_error": None}
    except OSError as exc:
        return {"argv": wrapper, "exit": None, "stdout": b"", "stderr": b"",
                "timed_out": False, "launch_error": str(exc)}


def run_read_only(repo, private_parent, argv, timeout):
    """Qualify the exact profile before passing the requested argv to it."""
    if sys.platform != "darwin":
        raise ValueError("read-only proof executor is unqualified on this host")
    runner = executable(argv[0])
    attempt = Path(tempfile.mkdtemp(prefix=".read-only-proof-", dir=private_parent))
    scratch = attempt / "scratch"
    scratch.mkdir(mode=0o700)
    protected = attempt / "protected"
    protected.write_bytes(b"qualified sentinel\n")
    (scratch / "alias").symlink_to(protected)
    executor = identity(scratch)
    probe_argv = [str(Path(sys.executable).resolve()), "-B", "-c", _PROBE, str(scratch), str(protected)]
    qualification = _execute(scratch, repo, probe_argv, 8)
    qualified = (
        qualification["exit"] == 0 and qualification["stdout"] == b"qualified read-only\n"
        and protected.read_bytes() == b"qualified sentinel\n" and (scratch / "own").is_file()
        and identity(scratch) == executor
    )
    result = _execute(scratch, repo, argv, timeout) if qualified else None
    return {"runner": runner, "executor": executor, "qualification": qualification, "result": result}


def verify_executor(executor, parent):
    scratch = Path(executor["scratch"])
    if (scratch.name != "scratch" or scratch.parent.parent != parent
            or not scratch.parent.name.startswith(".read-only-proof-")
            or scratch != scratch.resolve(strict=True)):
        raise ValueError("proof scratch identity is outside private executor storage")
    if identity(scratch) != executor:
        raise ValueError("proof executor host, tool or profile qualification changed")


GIT = Path("/usr/bin/git")
_NATIVE_TIMEOUT = 12
_RAW_LIMIT = 8 * 1024 * 1024
_TRANSPORT_LIMIT = 64 * 1024 * 1024
_CHUNK = 64 * 1024
_OID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_GIT_MODES = {b"100644": 0o644, b"100755": 0o755}
_GIT_CONFIG = {
    "core.hooksPath": "/dev/null",
    "core.fsmonitor": "false",
    "core.logAllRefUpdates": "false",
    "gc.auto": "0",
    "maintenance.auto": "false",
    "fetch.fsckObjects": "true",
    "fetch.recurseSubmodules": "false",
    "fetch.unpackLimit": "1",
    "fetch.writeCommitGraph": "false",
    "transfer.fsckObjects": "true",
    "protocol.version": "0",
    "pack.writeReverseIndex": "false",
    "submodule.recurse": "false",
}
_WORKER_FIELDS = {
    "prepare": {"ticket", "start", "predecessor", "mode"},
    "qualify": set(),
    "run": {"command"},
    "status": set(),
    "revoke": {"reason"},
    "submit": {"commit"},
    "admit": {"submission"},
    "cleanup": {"retained_commit"},
}


class WorkerHold(ValueError):
    """The operation has no qualified or safely reconciled outcome."""

    def __init__(self, message, receipt=None):
        super().__init__(message)
        self.receipt = receipt


def _directory(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or path != path.resolve(strict=True):
        raise ValueError("worker storage must be a canonical physical directory")
    return {"path": str(path), "device": info.st_dev, "inode": info.st_ino}


def _oid(value, *, length=None):
    if (not isinstance(value, str) or _OID.fullmatch(value) is None
            or (length is not None and len(value) != length)):
        raise ValueError("worker Git object requires a literal complete object ID")
    return value


def _git_env(scratch, *, local=False, helpers=None):
    env = {
        "PATH": "/usr/bin:/bin", "LANG": "C", "TMPDIR": str(scratch),
        "PYTHONDONTWRITEBYTECODE": "1", "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_ATTR_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1", "GIT_NO_LAZY_FETCH": "1",
        "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0",
        "GIT_ALLOW_PROTOCOL": "file" if local else "",
        "GIT_CONFIG_COUNT": str(len(_GIT_CONFIG)),
    }
    for index, (key, value) in enumerate(_GIT_CONFIG.items()):
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value
    if helpers is not None:
        env["GIT_EXEC_PATH"] = helpers
    return env


def _run(argv, cwd, env, *, data=b"", timeout=_NATIVE_TIMEOUT, fds=()):
    """Capture the native command, including a timeout or a launch refusal."""
    result = {"argv": argv, "cwd": str(cwd), "env": env, "pass_fds": list(fds)}
    try:
        completed = subprocess.run(argv, cwd=cwd, env=env, input=data, capture_output=True,
                                   close_fds=True, pass_fds=fds, timeout=timeout, check=False)
        return dict(result, exit=completed.returncode, stdout=completed.stdout, stderr=completed.stderr,
                    timed_out=False, launch_error=None)
    except subprocess.TimeoutExpired as exc:
        return dict(result, exit=None, stdout=exc.stdout or b"", stderr=exc.stderr or b"",
                    timed_out=True, launch_error=None)
    except OSError as exc:
        return dict(result, exit=None, stdout=b"", stderr=b"", timed_out=False, launch_error=str(exc))


def _git_argv(*args):
    return [str(GIT), "--no-replace-objects", "--literal-pathspecs", *map(str, args)]


def _git_ok(result, operation):
    if result["exit"] != 0:
        detail = (result["stderr"][:1024].decode(errors="replace").strip()
                  or result["launch_error"] or "native command did not complete")
        raise WorkerHold(f"{operation}: {detail}")
    return result["stdout"]


def _toolchain(cwd, scratch):
    if sys.platform != "darwin":
        raise WorkerHold("worker mode has no qualified sandbox on this host")
    env = _git_env(scratch)
    backend_result = _run(["/usr/bin/xcrun", "--find", "git"], cwd, env)
    helpers_result = _run([str(GIT), "--exec-path"], cwd, env)
    backend = Path(_git_ok(backend_result, "discover Git backend").decode().strip())
    helpers = Path(_git_ok(helpers_result, "discover Git helpers").decode().strip())
    _directory(helpers)
    selected = {}
    for name in ("git-upload-pack", "git-pack-objects", "git-fetch-pack",
                 "git-index-pack", "git-unpack-objects"):
        helper = helpers / name
        resolved = helper.resolve(strict=True)
        if resolved != backend and not resolved.is_relative_to(helpers):
            raise WorkerHold("Git helper is outside the selected developer toolchain")
        selected[str(helper)] = executable(resolved)
    kernel = os.uname()
    return {"sandbox": executable(SANDBOX), "git": executable(GIT), "backend": executable(backend),
            "helpers": str(helpers), "helper_executables": selected,
            "python": executable(Path(sys.executable).resolve()), "shell": executable(Path("/bin/sh")),
            "host": [kernel.sysname, kernel.release, kernel.version, kernel.machine], "protocol": 0}


def _sandbox_profile(*, directories, files=()):
    terms = [f"(subpath {json.dumps(str(path), ensure_ascii=False)})" for path in directories]
    terms.extend(f"(literal {json.dumps(str(path), ensure_ascii=False)})"
                 for path in (*files, Path("/dev/null")))
    rules = " ".join(f"(allow file-write* {term})" for term in terms)
    return ("(version 1) (deny default) (allow process-exec process-fork file-read* sysctl-read) "
            + rules + " (deny file-link)")


def _sandbox_argv(profile, argv):
    return [str(SANDBOX), "-p", profile, *argv]


def _read_regular(path, limit=_RAW_LIMIT):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("worker input must be a regular file without shared links")
        contents = stream.read(limit + 1)
    if len(contents) > limit:
        raise WorkerHold("worker input exceeds the qualified local byte limit")
    return contents


def _sha(contents):
    return hashlib.sha256(contents).hexdigest()


def _inventory(root, *, skip_git=False, contents=True):
    """Walk physical entries without following aliases, even in a dispatched clone."""
    device = _directory(root)["device"]
    files, dirs = {}, {}
    for folder, names, leaves in os.walk(root, followlinks=False):
        directory = Path(folder)
        if directory == root and skip_git:
            if ".git" not in names:
                raise ValueError("private worker clone has no independent Git directory")
            names.remove(".git")
        for name in sorted(names + leaves):
            path = directory / name
            info = path.lstat()
            relative = path.relative_to(root).as_posix()
            if info.st_dev != device or stat.S_ISLNK(info.st_mode):
                raise ValueError("worker storage contains an aliased or foreign-volume entry")
            mode = stat.S_IMODE(info.st_mode)
            if stat.S_ISDIR(info.st_mode):
                dirs[relative] = mode
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                files[relative] = {"mode": mode, "size": info.st_size}
                if contents:
                    files[relative]["sha256"] = _sha(_read_regular(path))
            else:
                raise ValueError("worker storage contains special files or shared links")
    return {"files": files, "directories": dirs}


def _object_name(name, oid_length):
    loose = re.fullmatch(rf"[0-9a-f]{{2}}/[0-9a-f]{{{oid_length - 2}}}", name)
    pack = re.fullmatch(rf"pack/pack-[0-9a-f]{{{oid_length}}}\.(?:pack|idx)", name)
    if loose is None and pack is None:
        raise ValueError("quarantine contains an unexpected object store entry")
    return name.split("/")


def _object_entries(parent, names):
    """Observe exact spellings, including the absence of case-fold aliases."""
    matching = {name.casefold(): name for name in names}
    entries = set()
    for entry in parent.iterdir():
        expected = matching.get(entry.name.casefold())
        if expected is not None:
            if expected != entry.name:
                raise WorkerHold("integration object path has a case-fold alias")
            entries.add(entry.name)
    return entries


def _object_directory(path, device):
    info = path.lstat()
    mode = stat.S_IMODE(info.st_mode)
    if (not stat.S_ISDIR(info.st_mode) or path != path.resolve(strict=True)
            or info.st_dev != device or mode & 0o7000):
        raise WorkerHold("integration object directory has an unqualified physical identity or mode")
    return {"device": info.st_dev, "inode": info.st_ino, "mode": mode}


def _object_file(path, device):
    before = path.lstat()
    mode = stat.S_IMODE(before.st_mode)
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or before.st_dev != device or mode & 0o7000):
        raise WorkerHold("object file has an unqualified physical identity or mode")
    raw = _read_regular(path)
    after = path.lstat()
    fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_ctime_ns", "st_mtime_ns")
    if before.st_size != len(raw) or any(getattr(before, key) != getattr(after, key) for key in fields):
        raise WorkerHold("object file changed during physical observation")
    return {"device": before.st_dev, "inode": before.st_ino, "mode": mode, "size": len(raw), "sha256": _sha(raw)}


def _object_effect(repo, names, oid_length):
    git = repo / ".git"
    device = _directory(git)["device"]
    if "objects" not in _object_entries(git, {"objects"}):
        raise WorkerHold("integration object store directory is missing")
    root = git / "objects"
    directories, files, parents = {".": _object_directory(root, device)}, {}, {}
    for name in names:
        parent, leaf = _object_name(name, oid_length)
        parents.setdefault(parent, []).append(leaf)
    present = _object_entries(root, parents)
    for parent, leaves in sorted(parents.items()):
        folder = root / parent
        directories[parent] = _object_directory(folder, device) if parent in present else None
        entries = _object_entries(folder, leaves) if parent in present else set()
        for leaf in sorted(leaves):
            files[parent + "/" + leaf] = _object_file(folder / leaf, device) if leaf in entries else None
    return {"directories": directories, "files": files}


def _matches_object_slot(actual, expected):
    if actual is None or expected is None:
        return actual is expected
    # A new directory has a bound device and mode; its inode is observed only after creation.
    return all(actual.get(key) == value for key, value in expected.items())


def _git_metadata(root, *, saved=None, bare=False):
    directory = root if bare else root / ".git"
    identity = _directory(directory)
    layout = _inventory(directory, contents=False)
    names = set(layout["files"]) | set(layout["directories"])
    forbidden = {"commondir", "gitdir", "shallow", "info/grafts", "objects/info/alternates",
                 "objects/info/http-alternates", "refs/replace", "modules", "worktrees"}
    if (names & forbidden or any(name.startswith(("refs/replace/", "hooks/"))
                                 or name.endswith(".promisor") for name in names)):
        raise ValueError("Git metadata has an unsupported hook, replacement, alternate or topology")
    if "packed-refs" in names and b" refs/replace/" in _read_regular(directory / "packed-refs"):
        raise ValueError("Git packed refs contain an unsupported replacement")
    config = _read_regular(directory / "config")
    if re.search(rb"(?im)^\s*\[\s*(?:include(?:if)?\b|extensions\b)", config):
        # The SHA-256 object format is supported without other extensions.
        permitted = re.sub(rb"(?im)^\s*\[\s*extensions\s*\]\s*\n\s*objectformat\s*=\s*sha256\s*$", b"", config)
        if re.search(rb"(?im)^\s*\[\s*(?:include(?:if)?\b|extensions\b)", permitted):
            raise ValueError("Git configuration uses an unqualified include or extension")
    observed = {"directory": identity, "config_sha256": _sha(config)}
    if saved is not None and observed != saved:
        raise ValueError("Git metadata or repository configuration changed")
    return observed


def _file_profile(attempt):
    clone, scratch = Path(attempt["root"]), Path(attempt["scratch"])
    dirs = [scratch]
    if attempt["phase"]["mode"] != "VERIFY":
        dirs.append(clone / ".git")
    return _sandbox_profile(directories=dirs, files=tuple(clone / path for path in attempt["phase"]["paths"]))


_WORKER_PROBE = """import fcntl, os, socket, subprocess, sys
from pathlib import Path

scratch, sentinel, alias = map(Path, sys.argv[1:4])
descriptor, port = map(int, sys.argv[4:6])
def denied(path):
    try:
        with path.open('ab'):
            pass
    except PermissionError:
        return
    raise SystemExit('protected file accepted a writer')

(scratch / 'qualified').write_text('worker scratch is writable')
with open('/dev/null', 'r+b') as device:
    assert device.read(1) == b''
denied(sentinel)
denied(alias)
try:
    os.link(sentinel, scratch / 'foreign-link')
except PermissionError:
    pass
else:
    raise SystemExit('foreign hard link was permitted')
try:
    fcntl.fcntl(descriptor, fcntl.F_GETFD)
except OSError:
    pass
else:
    raise SystemExit('ambient file descriptor was inherited')
try:
    socket.create_connection(('127.0.0.1', port), timeout=2).close()
except PermissionError:
    pass
else:
    raise SystemExit('local network was permitted')
child = "import subprocess,sys; raise SystemExit(subprocess.run([sys.executable,'-B','-c',sys.argv[1],sys.argv[2]],input=b'').returncode)"
grandchild = "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('unqualified grandchild')"
result = subprocess.run([sys.executable, '-B', '-c', child, grandchild, str(sentinel)],
                        input=b'', capture_output=True, close_fds=True, check=False)
if result.returncode == 0 or b'PermissionError' not in result.stderr:
    raise SystemExit('descendant write was not denied')
for name in sys.argv[6:]:
    path = Path(name)
    if path.exists():
        with path.open('ab'):
            pass
    else:
        path.touch(exist_ok=False)
        path.unlink()
print('qualified literal worker grants')
"""


_SOURCE_PROBE = """from pathlib import Path
import subprocess, sys

scratch = Path(sys.argv[1])
(scratch / 'source-qualified').write_text('source scratch is writable')
with open('/dev/null', 'r+b') as device:
    assert device.read(1) == b''
child = "from pathlib import Path; import sys; Path(sys.argv[1]).open('ab').close()"
for label, path in zip(('quarantine', 'integration', 'evidence', 'worker', 'relay'), sys.argv[2:]):
    result = subprocess.run([sys.executable, '-B', '-c', child, path],
                            input=b'', capture_output=True, close_fds=True, check=False)
    if result.returncode == 0 or b'PermissionError' not in result.stderr:
        raise SystemExit(label + ' write was not denied')
    print(label + ' write denied')
"""


_RELAY = """import fcntl, json, os, select, stat, sys, threading, time

source, reader, writer, read_identity, write_identity, canary, scratch, deadline, limit = CONFIG
if sys.argv[1:] != [source]:
    raise SystemExit('unexpected upload-pack relay arguments')
for fd, expected, mode in ((reader, read_identity, os.O_RDONLY), (writer, write_identity, os.O_WRONLY)):
    info = os.fstat(fd)
    if (not stat.S_ISFIFO(info.st_mode) or (info.st_dev, info.st_ino) != expected
            or fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE != mode):
        raise SystemExit('unexpected upload-pack relay descriptor')
try:
    os.fstat(canary)
except OSError:
    pass
else:
    raise SystemExit('ambient descriptor reached the relay')
print(json.dumps({'relay': 'qualified', 'fd': [reader, writer], 'source': source}),
      file=sys.stderr, flush=True)
stopping = threading.Event()
errors = []

def wait(fd, writing):
    while not stopping.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('protocol relay deadline expired')
        readable, writable, _ = select.select([] if writing else [fd], [fd] if writing else [],
                                               [], min(remaining, 0.05))
        if readable or writable:
            return True
    return False

def copy(source_fd, destination_fd, trace):
    count = 0
    try:
        os.set_blocking(source_fd, False)
        os.set_blocking(destination_fd, False)
        with open(os.path.join(scratch, trace), 'xb', buffering=0) as output:
            while wait(source_fd, False):
                try:
                    chunk = os.read(source_fd, 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    break
                count += len(chunk)
                if count > limit:
                    raise ValueError('protocol relay byte limit exceeded')
                pending = memoryview(chunk)
                while pending and wait(destination_fd, True):
                    try:
                        written = os.write(destination_fd, pending)
                    except BlockingIOError:
                        continue
                    output.write(pending[:written])
                    pending = pending[written:]
                if pending:
                    raise ValueError('protocol relay ended with undelivered bytes')
    except (OSError, ValueError) as error:
        errors.append(str(error))
        stopping.set()
    finally:
        os.close(destination_fd)

request = threading.Thread(target=copy, args=(0, writer, 'request.raw'))
request.start()
copy(reader, 1, 'response.raw')
stopping.set()
request.join()
if errors:
    raise SystemExit('; '.join(errors))
"""


class _PipeCapture:
    """Drain a native output pipe without an unbounded communicate buffer."""

    def __init__(self, deadline):
        self.read, self.write = os.pipe()
        self.deadline = deadline
        self.output = bytearray()
        self.error = None
        self.interruption = None
        self.reader = threading.Thread(target=self._drain, daemon=True)
        self.reader.start()

    def _drain(self):
        try:
            while True:
                ready, _, _ = select.select([self.read], [], [], max(0, self.deadline - time.monotonic()))
                if not ready:
                    self.error = "native stream deadline expired"
                    return
                data = os.read(self.read, _CHUNK)
                if not data:
                    return
                remaining = _RAW_LIMIT - len(self.output)
                self.output.extend(data[:remaining])
                if len(data) > remaining:
                    self.error = "native output exceeded the raw evidence limit"
                    return
        except OSError as exc:
            self.error = str(exc)
        finally:
            os.close(self.read)

    def close_writer(self):
        fd, self.write = self.write, None
        if fd is not None:
            os.close(fd)

    def finish(self):
        try:
            self.close_writer()
            self.reader.join(max(0, self.deadline - time.monotonic()) + 0.1)
        except KeyboardInterrupt:
            self.interruption = "KeyboardInterrupt while draining native output"
        else:
            if self.reader.is_alive():
                self.error = "native output pipe could not be sealed"
        return bytes(self.output)


def _pipe_identity(fd):
    info = os.fstat(fd)
    if not stat.S_ISFIFO(info.st_mode):
        raise ValueError("protocol endpoint is not an anonymous pipe")
    return info.st_dev, info.st_ino


def _wait_source(process, deadline, result):
    while True:
        try:
            result["exit"] = process.wait(timeout=max(0.1, deadline - time.monotonic()))
            return
        except KeyboardInterrupt:
            result["interruption"] = "KeyboardInterrupt while waiting for native source"
            if time.monotonic() >= deadline:
                result["exit"] = process.poll()
                return
        except subprocess.TimeoutExpired:
            result["timed_out"] = True
            try:
                process.kill()
                result["exit"] = process.wait(timeout=0.1)
            except KeyboardInterrupt:
                result["interruption"] = "KeyboardInterrupt while collecting native source status"
                result["exit"] = process.poll()
            except subprocess.TimeoutExpired:
                result["exit"] = process.poll()
            return


def _transport(source, quarantine, workspace, toolchain, commit, canary):
    """Run separate source and receiver sandboxes over exactly two relay endpoints."""
    relay = workspace / "fixed-relay"
    if re.fullmatch(r"/[A-Za-z0-9/_.-]+", str(relay)) is None:
        raise WorkerHold("native Git relay path is outside its qualified shell-neutral spelling")
    source_scratch, receiver_scratch = workspace / "source-scratch", workspace / "receiver-scratch"
    source_profile = _sandbox_profile(directories=(source_scratch,))
    receiver_profile = _sandbox_profile(directories=(quarantine, receiver_scratch))
    source_argv = _sandbox_argv(source_profile, _git_argv("upload-pack", "--strict", "--timeout=8", source))
    receive_argv = _sandbox_argv(receiver_profile, _git_argv(
        "fetch", "--no-tags", "--no-recurse-submodules", "--no-auto-maintenance",
        "--no-write-fetch-head", f"--upload-pack={relay}", source.as_uri(),
        f"{commit}:refs/quarantine/submitted",
    ))
    source_env = _git_env(source_scratch, helpers=toolchain["helpers"])
    receive_env = _git_env(receiver_scratch, local=True, helpers=toolchain["helpers"])
    deadline = time.monotonic() + _NATIVE_TIMEOUT
    source_error = _PipeCapture(deadline)
    receive_output = _PipeCapture(deadline)
    receive_error = _PipeCapture(deadline)
    source_result = {"argv": source_argv, "cwd": str(workspace), "env": source_env,
                     "exit": None, "launch_error": None, "timed_out": False, "pass_fds": [],
                     "interruption": None}
    receive_result = {"argv": receive_argv, "cwd": str(quarantine), "env": receive_env,
                      "exit": None, "launch_error": None, "timed_out": False, "interruption": None}
    source_process = None
    with contextlib.ExitStack() as pipes:
        read_request, write_request = [pipes.enter_context(os.fdopen(fd, mode, buffering=0))
                                      for fd, mode in zip(os.pipe(), ("rb", "wb"))]
        read_reply, write_reply = [pipes.enter_context(os.fdopen(fd, mode, buffering=0))
                                  for fd, mode in zip(os.pipe(), ("rb", "wb"))]
        relay_fds = (read_reply.fileno(), write_request.fileno())
        expected_pipes = tuple(_pipe_identity(fd) for fd in relay_fds)
        values = (str(source), *relay_fds, *expected_pipes, canary, str(receiver_scratch),
                  deadline, _TRANSPORT_LIMIT)
        program = (f"#!{toolchain['python']['path']}\nCONFIG = {values!r}\n" + _RELAY).encode()
        with relay.open("xb") as stream:
            stream.write(program)
            os.fchmod(stream.fileno(), 0o500)
            os.fsync(stream.fileno())
        binding = {"relay": executable(relay), "relay_parent": _directory(workspace),
                   "quarantine": _directory(quarantine), "source": _directory(source),
                   "pipe_identities": [list(row) for row in expected_pipes], "toolchain": toolchain}
        if binding["relay"]["sha256"] != _sha(program):
            raise WorkerHold("fixed relay bytes differ before execution")
        receive_result["pass_fds"] = list(relay_fds)
        try:
            source_process = subprocess.Popen(source_argv, cwd=workspace, env=source_env,
                                              stdin=read_request, stdout=write_reply, stderr=source_error.write,
                                              close_fds=True)
        except KeyboardInterrupt:
            source_result["interruption"] = "KeyboardInterrupt while launching native source"
        except OSError as exc:
            source_result["launch_error"] = str(exc)
        finally:
            read_request.close()
            write_reply.close()
            source_error.close_writer()
        if source_process is not None:
            try:
                completed = subprocess.run(
                    receive_argv, cwd=quarantine, env=receive_env, input=b"",
                    stdout=receive_output.write, stderr=receive_error.write,
                    close_fds=True, pass_fds=relay_fds, timeout=max(0.1, deadline - time.monotonic()),
                    check=False,
                )
                receive_result["exit"] = completed.returncode
            except KeyboardInterrupt:
                # subprocess.run does not expose a completed status on interruption.
                receive_result["interruption"] = "KeyboardInterrupt during native receiver execution"
            except subprocess.TimeoutExpired:
                receive_result["timed_out"] = True
            except OSError as exc:
                receive_result["launch_error"] = str(exc)
            finally:
                read_reply.close()
                write_request.close()
                receive_output.close_writer()
                receive_error.close_writer()
            _wait_source(source_process, deadline, source_result)
    source_result.update(stdout=b"", stderr=source_error.finish(), stream_error=source_error.error)
    source_result["interruption"] = source_result["interruption"] or source_error.interruption
    receive_result.update(stdout=receive_output.finish(), stderr=receive_error.finish())
    receive_result["stream_error"] = receive_output.error or receive_error.error
    receive_result["interruption"] = (receive_result["interruption"] or receive_output.interruption
                                      or receive_error.interruption)
    return {"binding": binding, "source": source_result, "receiver": receive_result,
            "trace": receiver_scratch}


def _write_private(path, content, mode=0o600):
    with path.open("xb") as stream:
        os.fchmod(stream.fileno(), mode)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _tree(repo, commit, env, contract, core):
    result = _run(_git_argv("ls-tree", "-r", "-z", "--full-tree", commit), repo, env)
    raw = _git_ok(result, "read literal Git tree")
    if raw and not raw.endswith(b"\0"):
        raise ValueError("Git tree did not return a complete NUL-delimited inventory")
    entries = {}
    for record in raw.split(b"\0")[:-1]:
        fields, separator, path = record.partition(b"\t")
        mode, kind, oid = fields.split()
        name = path.decode("utf-8")
        if not separator or kind != b"blob" or mode not in _GIT_MODES or name in entries:
            raise ValueError("Git tree contains an unsupported mode, object kind or duplicate path")
        entries[name] = {"mode": _GIT_MODES[mode], "oid": _oid(oid.decode("ascii"), length=len(commit))}
    contract.validate_file_domain(entries, core)
    return entries


def _blob(repo, oid, env):
    declared = _git_ok(_run(_git_argv("cat-file", "-s", oid), repo, env), "read Git blob size")
    size = int(declared.strip())
    if not 0 <= size <= _RAW_LIMIT:
        raise WorkerHold("Git blob exceeds the qualified local byte limit")
    raw = _git_ok(_run(_git_argv("cat-file", "blob", oid), repo, env), "read literal Git blob")
    algorithm = hashlib.sha1 if len(oid) == 40 else hashlib.sha256
    if len(raw) != size or algorithm(f"blob {size}\0".encode() + raw).hexdigest() != oid:
        raise ValueError("Git blob bytes do not match their literal object identity")
    return raw


def _verify_materialized(repo, tree, env, *, preserve_untracked=False):
    inventory = _inventory(repo, skip_git=True)
    actual = set(inventory["files"])
    if not set(tree) <= actual or (not preserve_untracked and actual != set(tree)):
        raise ValueError("materialized file inventory differs from the exact named Git tree")
    for name, row in tree.items():
        raw = _blob(repo, row["oid"], env)
        material = inventory["files"][name]
        mode = material["mode"]
        # Git represents the owner-executable class of a regular file.
        git_mode = 0o755 if mode & stat.S_IXUSR else 0o644
        if (mode & 0o7000 or git_mode != row["mode"]
                or material["size"] != len(raw) or material["sha256"] != _sha(raw)):
            raise ValueError("materialized file bytes or modes differ from the exact named Git tree")
    return inventory


def _raw_commit(repo, commit, predecessor, env):
    kind = _git_ok(_run(_git_argv("cat-file", "-t", commit), repo, env), "read named Git object type")
    if kind != b"commit\n":
        raise ValueError("submitted Git object is not a commit")
    size = int(_git_ok(_run(_git_argv("cat-file", "-s", commit), repo, env), "read commit size").strip())
    if not 0 <= size <= _RAW_LIMIT:
        raise WorkerHold("submitted commit exceeds the qualified local byte limit")
    raw = _git_ok(_run(_git_argv("cat-file", "commit", commit), repo, env), "read raw Git commit")
    headers, separator, _ = raw.partition(b"\n\n")
    fields = headers.splitlines()
    trees = [line[5:] for line in fields if line.startswith(b"tree ")]
    parents = [line[7:] for line in fields if line.startswith(b"parent ")]
    algorithm = hashlib.sha1 if len(commit) == 40 else hashlib.sha256
    if (not separator or len(raw) != size or algorithm(f"commit {size}\0".encode() + raw).hexdigest() != commit
            or len(trees) != 1 or parents != [predecessor.encode()] or fields[0] != b"tree " + trees[0]):
        raise ValueError("submitted raw commit must have the exact single admitted parent and one tree")
    return _oid(trees[0].decode("ascii"), length=len(commit))


def _integration_refs(repo, env):
    raw = _git_ok(_run(_git_argv("for-each-ref", "--format=%(refname)%00%(objectname)%00%(symref)"),
                       repo, env), "read integration refs")
    refs = {}
    for row in raw.splitlines():
        name, oid, symbolic = row.decode("utf-8").split("\0")
        if name in refs:
            raise ValueError("duplicate integration ref identity")
        refs[name] = {"oid": _oid(oid), "symbolic": symbolic}
    return {"head": _read_regular(repo / ".git" / "HEAD").decode("ascii"), "refs": refs}


def _retaining_ref(repo, env, predecessor, selected=None):
    commit = predecessor["commit"]
    raw = _git_ok(_run(_git_argv(
        "for-each-ref", f"--contains={commit}", "--format=%(refname)%00%(objectname)%00%(symref)%00%(objecttype)",
        "refs/heads/", "refs/i2e/admitted/",
    ), repo, env), "observe durable integration refs that retain the predecessor")
    candidates = {}
    for line in raw.splitlines():
        name, oid, symbolic, kind = line.decode("utf-8").split("\0")
        if name in candidates:
            raise WorkerHold("cleanup retaining ref has an ambiguous native identity")
        if not symbolic and kind == "commit":
            candidates[name] = _oid(oid, length=len(commit))
    if predecessor["ref"] is not None:
        selected = predecessor["ref"]
        if candidates.get(selected) != commit:
            raise WorkerHold("the exact admitted predecessor ref no longer retains its commit")
    if selected is None:
        head = _read_regular(repo / ".git" / "HEAD").decode("ascii").strip()
        if head.startswith("ref: ") and head[5:] in candidates:
            selected = head[5:]
        elif len(candidates) == 1:
            selected = next(iter(candidates))
    if (selected not in candidates
            or sum(name.casefold() == selected.casefold() for name in candidates) != 1):
        raise WorkerHold("cleanup requires an unambiguous durable integration ref retaining the exact commit")
    return {"ref": selected, "oid": candidates[selected], "commit": commit}


def _reserved_ref_absent(repo, ref, refs):
    folder = repo / ".git"
    parts = ref.split("/")
    for index, component in enumerate(parts):
        if not folder.exists():
            break
        if not stat.S_ISDIR(folder.lstat().st_mode) or folder != folder.resolve(strict=True):
            raise ValueError("integration ref has an aliased or conflicting ancestor")
        matches = [entry.name for entry in folder.iterdir() if entry.name.casefold() == component.casefold()]
        if matches and (matches != [component] or index == len(parts) - 1):
            raise ValueError("reserved integration ref already has a physical entry or alias")
        folder /= component
    if any(name == ref or name.startswith(ref + "/") or ref.startswith(name + "/") for name in refs["refs"]):
        raise ValueError("reserved integration ref conflicts with an existing ref")


@contextlib.contextmanager
def _integration_lock(repo, identity):
    """Retain the same open-file description for any trusted native ref writer."""
    import fcntl

    directory = repo / ".git"
    try:
        observed = _directory(directory)
        if observed != identity:
            raise ValueError("integration guard path or inode changed")
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except (ValueError, OSError) as exc:
        raise WorkerHold("integration guard identity could not be established: " + str(exc)) from exc
    try:
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) != (identity["device"], identity["inode"]):
            raise WorkerHold("integration guard descriptor differs from its pinned inode")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            observed = _directory(directory)
        except BlockingIOError as exc:
            raise WorkerHold("integration guard is held by a possible native writer") from exc
        except (ValueError, OSError) as exc:
            raise WorkerHold("integration guard could not be revalidated: " + str(exc)) from exc
        if observed != identity:
            raise WorkerHold("integration guard topology changed before use")
        yield fd
    finally:
        # Closing our descriptor leaves any native writer's inherited lock held.
        os.close(fd)


class Worker:
    def __init__(self, ledger, runtime):
        self.ledger = ledger
        self.runtime = runtime
        self.core = runtime.core
        self.contract = runtime.contract

    def apply(self, state, operation, expected_seq, request):
        try:
            if operation not in _WORKER_FIELDS:
                raise ValueError("unsupported worker operation")
            self.contract.fields(request, {"id", "actor", "attempt"} | _WORKER_FIELDS[operation],
                                 "worker request")
            self.core.canonical(request)
            for key in ("id", "actor", "attempt"):
                self.core._label(request[key], f"worker {key}")
            if request["id"].startswith("i2e/") or type(expected_seq) is not int or expected_seq < 0:
                raise ValueError("worker request needs a public ID and exact nonnegative sequence")
            self._authority(state, operation)
            if operation == "admit":
                intent = self._by_request(state, "worker_admission_intent", request)
                if intent is not None:
                    return self._reconcile(state, expected_seq, request, intent)
            if state["seq"] != expected_seq:
                raise ValueError("expected sequence conflict; worker request is stale")
            return getattr(self, f"_{operation}")(state, request)
        except WorkerHold as exc:
            result = {"state": "HOLD", "errors": [str(exc)]}
            if exc.receipt is not None:
                result["receipt"] = exc.receipt
            return result
        except (self.core.RuntimeError, ValueError, OSError, TypeError, KeyError) as exc:
            return {"state": "BLOCK", "errors": [str(exc)]}

    def _authority(self, state, operation):
        if state["contract"]["synthetic"] is not True:
            raise WorkerHold("operational model workers have no qualified transport in this mode")
        authority = state["contract"]["authority"]
        needed = {"edit", "worker"}
        if operation == "cleanup":
            needed.add("cleanup")
        self.core.verify_reference(authority["evidence"])
        if not needed <= set(authority["actions"]):
            raise ValueError("worker operation lacks recorded local action authority")

    def _event(self, kind, request, data):
        return {"id": self.core._internal_id(kind, request["id"]), "type": kind, "data": data}

    def _by_request(self, state, kind, request):
        key = self._event(kind, request, {})["id"]
        return self.core._latest(state, kind, lambda event: event["id"] == key)

    def _append(self, state, kind, request, data, guard=None):
        if self._by_request(state, kind, request) is not None:
            raise ValueError("worker operation ID is already recorded")
        return self.ledger._append(state["contract"]["run_id"], self._event(kind, request, data),
                                   state["seq"], internal=True, guard=guard)

    def _storage(self, state, prefix):
        parent = self.core._safe_path(self.ledger.db.parent / "worker-runs")
        repo = Path(state["contract"]["repo"])
        package = Path(__file__).resolve().parents[1]
        blocked = (repo, package, Path(state["contract"]["case_store"]), Path(state["evidence_root"]))
        if any(parent.is_relative_to(path) or path.is_relative_to(parent) for path in blocked):
            raise ValueError("worker storage overlaps protected integration, package or evidence")
        parent.mkdir(mode=0o700, exist_ok=True)
        _directory(parent)
        run = parent / _sha(state["contract"]["run_id"].encode())
        run.mkdir(mode=0o700, exist_ok=True)
        _directory(run)
        return Path(tempfile.mkdtemp(prefix=prefix, dir=run))

    def _receipt(self, parent, name, result):
        directory = parent / name
        directory.mkdir(mode=0o700)
        receipt = {key: value for key, value in result.items() if key not in {"stdout", "stderr"}}
        for channel in ("stdout", "stderr"):
            path = directory / channel
            _write_private(path, result[channel])
            if len(result[channel]) <= self.core.MAX_FILE_BYTES:
                receipt[channel] = self.core.reference(path)
            else:
                receipt[channel] = {"path": str(path), "sha256": _sha(result[channel]), "oversized": True}
        path = directory / "command.json"
        _write_private(path, self.core.canonical(receipt))
        self.core._sync_directory(directory)
        return self.core.reference(path)

    def _recent(self, state, kind, attempt):
        return self.core._latest(state, kind, lambda event: event["data"].get("attempt") == attempt["id"])

    def _attempt(self, state, request):
        event = self.core._latest(state, "worker_attempt",
                                  lambda row: row["data"]["id"] == request["attempt"])
        if event is None or event["data"]["actor"] != request["actor"]:
            raise ValueError("worker attempt or its recorded actor is missing")
        return event["data"]

    def _accepted(self, state):
        return self.core._latest(state, "worker_admission_result",
                                 lambda event: event["data"]["outcome"] == "INTENDED")

    def _predecessor(self, state):
        accepted = self._accepted(state)
        if accepted is None:
            return {"commit": state["contract"]["source"]["base"], "ref": None, "result": None}
        row = accepted["data"]
        return {"commit": row["commit"], "ref": row["ref"], "result": accepted["id"]}

    def _phase(self, state, request, attempt, *, own_intent=None, reconciling=False):
        if self._recent(state, "worker_revocation", attempt) or self._recent(state, "worker_cleanup_intent", attempt):
            raise ValueError("worker attempt was retired or its clone is being removed")
        phase = self.runtime.worker_phase(state, attempt["phase"]["start"], request["actor"], attempt["ticket"],
                                          own_intent=own_intent, resolved_readback=reconciling)
        if reconciling:
            if dict(phase, candidate=attempt["phase"]["candidate"]) != attempt["phase"]:
                raise ValueError("worker phase or grants changed before reconciliation")
        elif phase != attempt["phase"] or self._predecessor(state) != attempt["predecessor"]:
            raise ValueError("worker generation has a stale candidate or admitted predecessor")
        return phase

    def _storage_identity(self, attempt):
        for key in ("root", "scratch"):
            if _directory(Path(attempt[key])) != attempt[key + "_identity"]:
                raise ValueError("worker generation storage identity changed")

    def _prepared_toolchain(self, attempt, repo):
        self._storage_identity(attempt)
        if _toolchain(repo, Path(attempt["scratch"])) != attempt["toolchain"]:
            raise WorkerHold("qualified worker toolchain changed")
        return attempt["toolchain"]

    def _prepare(self, state, request):
        if request["mode"] != MODE or state["contract"]["executor_mode"] != MODE:
            raise WorkerHold("requested worker mode is unsupported")
        if self.core._latest(state, "worker_attempt", lambda row: row["data"]["id"] == request["attempt"]):
            raise ValueError("worker attempt ID already exists")
        phase = self.runtime.worker_phase(state, request["start"], request["actor"], request["ticket"])
        predecessor = self._predecessor(state)
        commit = _oid(request["predecessor"], length=len(predecessor["commit"]))
        if predecessor["commit"] != commit:
            raise ValueError("worker must use the exact current admitted predecessor")
        root = self._storage(state, "generation-")
        clone, scratch = root / "clone", root / "scratch"
        scratch.mkdir(mode=0o700)
        repo = Path(state["contract"]["repo"])
        integration = _git_metadata(repo)
        toolchain = _toolchain(repo, scratch)
        env = _git_env(scratch, local=True, helpers=toolchain["helpers"])
        refs = _integration_refs(repo, env)
        if predecessor["ref"] is not None and refs["refs"].get(predecessor["ref"]) != {"oid": commit, "symbolic": ""}:
            raise ValueError("named admitted predecessor ref differs from its durable identity")
        tree = _tree(repo, commit, env, self.contract, self.core)
        baseline = _verify_materialized(repo, tree, env, preserve_untracked=True)
        candidate = phase["candidate"]
        for name, checksum in (candidate["files"] | candidate["instructions"]).items():
            row = tree.get(name)
            if checksum is None:
                if row is not None or name in baseline["files"]:
                    raise ValueError("phase-absent file is present in the admitted tree or worktree")
            elif (row is None or baseline["files"][name]["sha256"] != checksum
                  or self.contract.git_mode(row["mode"]) != candidate["modes"][name]):
                raise ValueError("phase-owned source bytes or modes differ from the exact admitted tree")
        cloned = _run(_git_argv("clone", "--no-local", "--no-hardlinks", "--no-checkout",
                                "--no-tags", "--template=", "--", repo.as_uri(), clone), root, env)
        clone_receipt = self._receipt(root, "clone-command", cloned)
        _git_ok(cloned, "create independent worker clone")
        _git_metadata(clone)
        fetch_receipt = None
        if predecessor["ref"] is not None:
            fetched = _run(_git_argv("fetch", "--no-tags", "--no-recurse-submodules",
                                     "--no-auto-maintenance", "--no-write-fetch-head",
                                     repo.as_uri(), commit), clone, env)
            fetch_receipt = self._receipt(root, "predecessor-command", fetched)
            _git_ok(fetched, "retrieve exact admitted predecessor")
        checked = _run(_git_argv("checkout", "--detach", commit), clone, env)
        checkout_receipt = self._receipt(root, "checkout-command", checked)
        _git_ok(checked, "materialize exact worker predecessor")
        if _read_regular(clone / ".git" / "HEAD") != commit.encode() + b"\n":
            raise ValueError("worker clone HEAD is not the exact detached predecessor")
        if _tree(clone, commit, env, self.contract, self.core) != tree:
            raise ValueError("worker clone received different predecessor objects")
        _verify_materialized(clone, tree, env)
        for path in phase["paths"]:
            identity = self.contract.path_identity(clone, path, self.core)
            if len(identity["ancestors"]) != len(path.split("/")):
                raise ValueError("worker grant requires already registered physical parent directories")
        token = self.core.digest({"run": state["contract"]["run_id"], "attempt": request["attempt"]})
        attempt = {
            "id": request["attempt"], "actor": request["actor"], "ticket": request["ticket"],
            "generation": len(self.core._events(state, "worker_attempt")) + 1, "mode": MODE,
            "phase": phase, "predecessor": predecessor, "integration": integration,
            "integration_ref": f"refs/i2e/admitted/{token}", "toolchain": toolchain,
            "root": str(clone), "root_identity": _directory(clone),
            "scratch": str(scratch), "scratch_identity": _directory(scratch),
            "metadata": _git_metadata(clone), "inventory": self.core.digest(_inventory(clone)),
            "commands": {"clone": clone_receipt, "checkout": checkout_receipt, "fetch": fetch_receipt},
        }

        def guard(current):
            if (self.runtime.worker_phase(current, request["start"], request["actor"], request["ticket"]) != phase
                    or self._predecessor(current) != predecessor or _integration_refs(repo, env) != refs
                    or _git_metadata(repo) != integration):
                raise ValueError("worker preparation prerequisites changed during clone creation")
            if _verify_materialized(repo, tree, env, preserve_untracked=True) != baseline:
                raise ValueError("protected integration inventory changed during clone creation")

        self._append(state, "worker_attempt", request, attempt, guard)
        return {"state": "PASS", "errors": [], "attempt": dict(attempt, state="PREPARED")}

    def _status(self, state, request):
        attempt = self._attempt(state, request)
        status = "PREPARED"
        for kind, label in (
            ("worker_qualification", "QUALIFIED"), ("worker_dispatch_intent", "POSSIBLE_WRITER"),
            ("worker_dispatch_result", "DISPATCHED"), ("worker_submission", "SUBMITTED"),
            ("worker_admission_result", "ADMISSION_RECORDED"), ("worker_revocation", "REVOKED"),
            ("worker_cleanup_result", "CLEANED"),
        ):
            if self._recent(state, kind, attempt):
                status = label
        return {"state": "PASS", "errors": [], "attempt": dict(attempt, state=status)}

    def _qualify(self, state, request):
        import fcntl

        attempt = self._attempt(state, request)
        self._phase(state, request, attempt)
        if self._recent(state, "worker_qualification", attempt) or self._recent(state, "worker_dispatch_intent", attempt):
            raise ValueError("qualification requires a fresh, never-dispatched worker generation")
        repo, clone, scratch = Path(state["contract"]["repo"]), Path(attempt["root"]), Path(attempt["scratch"])
        toolchain = self._prepared_toolchain(attempt, repo)
        _git_metadata(clone, saved=attempt["metadata"])
        profile = _file_profile(attempt)
        env = _git_env(scratch, helpers=toolchain["helpers"])
        directory = self._storage(state, "qualification-")
        sentinel = directory / "protected"
        _write_private(sentinel, b"worker protected sentinel\n")
        alias = scratch / ("alias-" + directory.name)
        alias.symlink_to(sentinel)
        with sentinel.open("ab") as stream, socket.socket() as listener:
            canary = fcntl.fcntl(stream.fileno(), fcntl.F_DUPFD, 64)
            os.set_inheritable(canary, True)
            try:
                listener.bind(("127.0.0.1", 0))
                listener.listen()
                argv = [toolchain["python"]["path"], "-B", "-c", _WORKER_PROBE, str(scratch), str(sentinel),
                        str(alias), str(canary), str(listener.getsockname()[1]),
                        *(str(clone / name) for name in attempt["phase"]["paths"])]
                probe = _run(_sandbox_argv(profile, argv), clone, env)
            finally:
                os.close(canary)
        receipt = self._receipt(directory, "worker-probe", probe)
        if (probe["exit"] != 0 or probe["stdout"] != b"qualified literal worker grants\n"
                or _read_regular(sentinel) != b"worker protected sentinel\n"
                or self.core.digest(_inventory(clone)) != attempt["inventory"]):
            return {"state": "HOLD", "errors": ["native literal worker grants did not qualify"], "receipt": receipt}
        git = _run(_sandbox_argv(profile, _git_argv("rev-parse", "HEAD")), clone, env)
        git_receipt = self._receipt(directory, "git-probe", git)
        if git["exit"] != 0 or git["stdout"] != attempt["predecessor"]["commit"].encode() + b"\n":
            return {"state": "HOLD", "errors": ["native Git did not qualify under worker grants"], "receipt": git_receipt}
        data = {"attempt": attempt["id"], "profile": profile, "toolchain": toolchain,
                "worker_probe": receipt, "git_probe": git_receipt}
        self._append(state, "worker_qualification", request, data,
                     lambda current: self._phase(current, request, attempt))
        return {"state": "PASS", "errors": [], "qualification": data}

    def _qualification(self, state, attempt):
        qualification = self._recent(state, "worker_qualification", attempt)
        if qualification is None:
            raise WorkerHold("worker generation lacks an actual local sandbox qualification")
        data = qualification["data"]
        if data["profile"] != _file_profile(attempt) or data["toolchain"] != attempt["toolchain"]:
            raise WorkerHold("worker qualification no longer matches its generation")
        for key in ("worker_probe", "git_probe"):
            self.core.verify_reference(data[key])
        return qualification

    def _run(self, state, request):
        attempt = self._attempt(state, request)
        self._phase(state, request, attempt)
        qualification = self._qualification(state, attempt)
        if self._recent(state, "worker_dispatch_intent", attempt):
            raise WorkerHold("worker generation may already have a dispatched writer")
        command = request["command"]
        if (not isinstance(command, list) or not command or len(command) > 128
                or any(not isinstance(arg, str) or not arg or "\0" in arg for arg in command)):
            raise ValueError("worker command requires a bounded, literal argument array")
        runner = executable(command[0])
        repo = Path(state["contract"]["repo"])
        toolchain = self._prepared_toolchain(attempt, repo)
        directory = self._storage(state, "dispatch-")
        clone, scratch = Path(attempt["root"]), Path(attempt["scratch"])
        _git_metadata(clone, saved=attempt["metadata"])
        data = {"attempt": attempt["id"], "request": request, "qualification": qualification["id"],
                "runner": runner, "evidence": str(directory)}
        intent = self._append(state, "worker_dispatch_intent", request, data,
                              lambda current: self._phase(current, request, attempt))
        with self.ledger._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = self.ledger._read(conn, state["contract"]["run_id"])
            if current["sha256"] != intent["sha256"] or executable(command[0]) != runner:
                raise WorkerHold("worker dispatch prefix or runner changed before launch")
            self._phase(current, request, attempt)
            self._storage_identity(attempt)
            argv = _sandbox_argv(qualification["data"]["profile"], command)
            result = _run(argv, clone, _git_env(scratch, helpers=toolchain["helpers"]))
            receipt = self._receipt(directory, "command", result)
            self._phase(current, request, attempt)
            passed = result["exit"] == 0 and len(result["stdout"]) <= _RAW_LIMIT and len(result["stderr"]) <= _RAW_LIMIT
            record = {"attempt": attempt["id"], "intent": intent["id"], "receipt": receipt,
                      "exit": result["exit"], "passed": passed}
            self.ledger._insert_event(conn, current, self._event("worker_dispatch_result", request, record))
            conn.commit()
        return {"state": "PASS" if passed else "HOLD", "errors": [] if passed else ["native worker did not complete"],
                "receipt": receipt}

    def _revoke(self, state, request):
        attempt = self._attempt(state, request)
        self.contract.text(request["reason"], "worker revocation reason")
        if self._recent(state, "worker_revocation", attempt):
            raise ValueError("worker generation already has a recorded revocation")
        self._append(state, "worker_revocation", request, {"attempt": attempt["id"], "reason": request["reason"]})
        return {"state": "PASS", "errors": [], "attempt": dict(attempt, state="REVOKED")}

    def _submit(self, state, request):
        attempt = self._attempt(state, request)
        self._phase(state, request, attempt)
        self._qualification(state, attempt)
        dispatch = self._recent(state, "worker_dispatch_result", attempt)
        if dispatch is None or dispatch["data"]["passed"] is not True:
            raise ValueError("submission requires a completed qualified dispatch")
        if attempt["phase"]["mode"] == "VERIFY" or self._recent(state, "worker_submission", attempt):
            raise ValueError("this worker generation has no fresh writable submission")
        commit = _oid(request["commit"], length=len(attempt["predecessor"]["commit"]))
        clone = Path(attempt["root"])
        self._storage_identity(attempt)
        _git_metadata(clone, saved=attempt["metadata"])
        data = {"id": request["id"], "attempt": attempt["id"], "commit": commit, "dispatch": dispatch["id"]}

        def guard(current):
            self._phase(current, request, attempt)
            _git_metadata(clone, saved=attempt["metadata"])

        self._append(state, "worker_submission", request, data, guard)
        return {"state": "PASS", "errors": [], "submission": data}

    def _qualify_transport(self, state, attempt, workspace, quarantine, toolchain):
        repo = Path(state["contract"]["repo"])
        clone = Path(attempt["root"])
        scratch = workspace / "source-scratch"
        sentinel = workspace / "outside-peers"
        _write_private(sentinel, b"worker transport sentinel\n")
        protected = [quarantine / "config", repo / ".git" / "config", sentinel, clone / ".git" / "config", sentinel]
        before = [_read_regular(path) for path in protected]
        profile = _sandbox_profile(directories=(scratch,))
        probe = _run(_sandbox_argv(profile, [
            toolchain["python"]["path"], "-B", "-c", _SOURCE_PROBE, str(scratch), *map(str, protected),
        ]), workspace, _git_env(scratch, helpers=toolchain["helpers"]))
        receipt = self._receipt(workspace, "source-qualification", probe)
        expected = b"quarantine write denied\nintegration write denied\nevidence write denied\nworker write denied\nrelay write denied\n"
        if probe["exit"] != 0 or probe["stdout"] != expected or before != [_read_regular(path) for path in protected]:
            raise WorkerHold("native source-serving write boundary did not qualify", receipt)
        receiver_scratch = workspace / "receiver-scratch"
        receiver_profile = _sandbox_profile(directories=(quarantine, receiver_scratch))
        received = _run(_sandbox_argv(receiver_profile, _git_argv("rev-parse", "--is-bare-repository")),
                        quarantine, _git_env(receiver_scratch, helpers=toolchain["helpers"]))
        receiver_receipt = self._receipt(workspace, "receiver-qualification", received)
        if received["exit"] != 0 or received["stdout"] != b"true\n":
            raise WorkerHold("native quarantine receiver profile did not qualify", receiver_receipt)
        return sentinel, receipt, receiver_receipt

    def _stage(self, state, attempt, commit, predecessor_tree, toolchain):
        import fcntl

        root = self._storage(state, "admission-")
        quarantine = root / "quarantine.git"
        source = Path(attempt["root"]) / ".git"
        for name in ("source-scratch", "receiver-scratch", "payload", "import"):
            (root / name).mkdir(mode=0o700)
        env = _git_env(root / "receiver-scratch", helpers=toolchain["helpers"])
        git_format = "sha1" if len(commit) == 40 else "sha256"
        created = _run(_git_argv("init", "--bare", "--template=", f"--object-format={git_format}", quarantine), root, env)
        self._receipt(root, "quarantine-init", created)
        _git_ok(created, "create clean bare quarantine")
        metadata = _git_metadata(quarantine, bare=True)
        sentinel, source_probe, receiver_probe = self._qualify_transport(state, attempt, root, quarantine, toolchain)
        with sentinel.open("ab") as stream:
            canary = fcntl.fcntl(stream.fileno(), fcntl.F_DUPFD, 64)
            os.set_inheritable(canary, True)
            try:
                native = _transport(source, quarantine, root, toolchain, commit, canary)
            finally:
                os.close(canary)
        native_refs = {side: self._receipt(root, side + "-transfer", native[side]) for side in ("source", "receiver")}
        interruptions = {side: native[side]["interruption"] for side in native_refs if native[side]["interruption"]}
        if interruptions:
            partial = {}
            for name in ("request.raw", "response.raw"):
                try:
                    prefix = _read_regular(native["trace"] / name, _TRANSPORT_LIMIT)
                except (OSError, ValueError) as exc:
                    partial[name] = {"observation_error": str(exc)}
                    continue
                saved = root / ("cancelled-" + name)
                _write_private(saved, prefix)
                partial[name] = {"path": str(saved), "sha256": _sha(prefix), "bytes": len(prefix)}
            receipt = root / "cancelled-transfer.json"
            _write_private(receipt, self.core.canonical({
                "interruptions": interruptions, "peers": native_refs, "observed_protocol_prefixes": partial,
                "retained_quarantine": str(quarantine),
            }))
            self.core._sync_directory(root)
            raise WorkerHold("native Git transfer cancelled; quarantine and observed peer output retained",
                             self.core.reference(receipt))
        for side, receipt in native_refs.items():
            if native[side]["exit"] != 0 or native[side]["timed_out"] or native[side]["stream_error"]:
                raise WorkerHold(f"native {side} transfer did not establish complete quarantine", receipt)
        if b'"relay": "qualified"' not in native["receiver"]["stderr"]:
            raise WorkerHold("actual receiver did not demonstrate the fixed pipe relay", native_refs["receiver"])
        if _read_regular(sentinel) != b"worker transport sentinel\n":
            raise WorkerHold("worker transport changed its protected descriptor sentinel")
        _git_metadata(source.parent, saved=attempt["metadata"])
        _git_metadata(quarantine, saved=metadata, bare=True)
        receiver_profile = _sandbox_profile(directories=(quarantine, root / "receiver-scratch"))
        checked = _run(_sandbox_argv(receiver_profile, _git_argv("fsck", "--strict", "--full", "--no-reflogs", commit)),
                       quarantine, env)
        fsck_receipt = self._receipt(root, "strict-object-check", checked)
        _git_ok(checked, "verify complete quarantined objects")
        submitted = _git_ok(_run(_git_argv("rev-parse", "--verify", "refs/quarantine/submitted"), quarantine, env),
                            "read exact quarantined submission")
        if submitted != commit.encode() + b"\n":
            raise ValueError("receiver did not retain the exact named object")
        tree_id = _raw_commit(quarantine, commit, attempt["predecessor"]["commit"], env)
        tree = _tree(quarantine, commit, env, self.contract, self.core)
        delta = sorted(name for name in tree.keys() | predecessor_tree.keys()
                       if tree.get(name) != predecessor_tree.get(name))
        if not delta or not set(delta) <= set(attempt["phase"]["paths"]):
            raise ValueError("literal named Git delta is empty or exceeds this worker's approved paths")
        repo = Path(state["contract"]["repo"])
        changes = {}
        for name in delta:
            self.contract.require_writable_name(state["contract"], name, self.core)
            identity = self.contract.path_identity(repo, name, self.core)
            if len(identity["ancestors"]) != len(name.split("/")):
                raise ValueError("admitted file has an unregistered physical parent")
            if (identity["leaf"] is not None) != (name in predecessor_tree):
                raise ValueError("admission would replace untracked or missing integration evidence")
            change = {"before_identity": identity, "file": None, "after": None}
            if name in tree:
                row = tree[name]
                raw = _blob(quarantine, row["oid"], env)
                material = root / "payload" / _sha(name.encode())
                mode = row["mode"]
                if name in predecessor_tree and predecessor_tree[name]["mode"] == mode:
                    mode = identity["leaf"]["mode"]
                _write_private(material, raw, mode)
                change.update(file=self.core.reference(material),
                              after={"mode": mode, "size": len(raw), "sha256": _sha(raw)})
            changes[name] = change
        objects = _inventory(quarantine / "objects")
        for name, row in objects["files"].items():
            _object_name(name, len(commit))
            raw = _read_regular(quarantine / "objects" / name)
            if _sha(raw) != row["sha256"]:
                raise ValueError("quarantine object changed during controller import staging")
            _write_private(root / "import" / _sha(name.encode()), raw, 0o444)
        if not objects["files"]:
            raise ValueError("quarantine retained no physical Git objects")
        trace = {name: self.core.reference(native["trace"] / name) for name in ("request.raw", "response.raw")}
        proof = {"source_qualification": source_probe, "receiver_qualification": receiver_probe,
                 "transport": native_refs, "binding": native["binding"], "protocol_streams": trace,
                 "strict_objects": fsck_receipt}
        return {"root": _directory(root), "quarantine": metadata,
                "receiver_scratch": _directory(root / "receiver-scratch"),
                "import_storage": _directory(root / "import"), "commit": commit, "tree": tree_id,
                "objects": objects, "changes": changes, **proof}

    def _integrated(self, repo, attempt, env, stage=None):
        _git_metadata(repo, saved=attempt["integration"])
        result = {"inventory": _inventory(repo, skip_git=True), "refs": _integration_refs(repo, env)}
        if stage is not None:
            result["objects"] = _object_effect(repo, stage["objects"]["files"], len(stage["commit"]))
        return result

    def _plan_object_import(self, repo, stage):
        objects = stage["objects"]["files"]
        before = _object_effect(repo, objects, len(stage["commit"]))
        root = Path(stage["root"]["path"])
        device = before["directories"]["."]["device"]
        if _directory(root / "import") != stage["import_storage"]:
            raise WorkerHold("staged object import directory identity changed")
        sources, files = {}, {}
        for name, received in objects.items():
            source = _object_file(root / "import" / _sha(name.encode()), device)
            if (source["mode"] != 0o444 or source["size"] != received["size"]
                    or source["sha256"] != received["sha256"]):
                raise WorkerHold("staged raw object differs from the validated import bytes or mode")
            existing = before["files"][name]
            if existing is not None and any(existing[key] != source[key] for key in ("size", "sha256")):
                raise WorkerHold("existing Git object storage differs from the validated object")
            sources[name], files[name] = source, existing if existing is not None else source
        directories = {name: row if row is not None else {"device": device, "mode": 0o755}
                       for name, row in before["directories"].items()}
        return {"before": before, "after": {"files": files, "directories": directories}, "sources": sources}

    def _admit(self, state, request):
        attempt = self._attempt(state, request)
        self._phase(state, request, attempt)
        self._qualification(state, attempt)
        submitted = self._recent(state, "worker_submission", attempt)
        if submitted is None or submitted["data"]["id"] != request["submission"]:
            raise ValueError("admission requires the exact worker submission")
        if self._recent(state, "worker_admission_intent", attempt):
            raise ValueError("worker submission already has a durable admission intent")
        repo = Path(state["contract"]["repo"])
        toolchain = self._prepared_toolchain(attempt, repo)
        clone = Path(attempt["root"])
        _git_metadata(clone, saved=attempt["metadata"])
        env = _git_env(Path(attempt["scratch"]), helpers=toolchain["helpers"])
        before = self._integrated(repo, attempt, env)
        ref = attempt["integration_ref"]
        _reserved_ref_absent(repo, ref, before["refs"])
        predecessor = attempt["predecessor"]
        if predecessor["ref"] is not None and before["refs"]["refs"].get(predecessor["ref"]) != {
            "oid": predecessor["commit"], "symbolic": "",
        }:
            raise ValueError("integration predecessor ref changed before staging")
        predecessor_tree = _tree(repo, predecessor["commit"], env, self.contract, self.core)
        if _verify_materialized(repo, predecessor_tree, env, preserve_untracked=True) != before["inventory"]:
            raise ValueError("integration source changed while observing the exact admitted predecessor")
        commit = submitted["data"]["commit"]
        stage = self._stage(state, attempt, commit, predecessor_tree, toolchain)
        stage_root = Path(stage["root"]["path"])
        env = _git_env(stage_root / "receiver-scratch", helpers=toolchain["helpers"])
        files = dict(before["inventory"]["files"])
        for name, change in stage["changes"].items():
            if change["after"] is None:
                del files[name]
            else:
                files[name] = change["after"]
        after = {"inventory": dict(before["inventory"], files=files),
                 "refs": dict(before["refs"], refs=before["refs"]["refs"] | {ref: {"oid": commit, "symbolic": ""}})}
        record = {"attempt": attempt["id"], "request": request, "expected_seq": state["seq"],
                  "submission": submitted["id"], "ref": ref, "commit": commit,
                  "predecessor": predecessor, "phase": attempt["phase"],
                  "guard": attempt["integration"]["directory"], "before": before, "after": after, "stage": stage}
        payload = f"start\ncreate {ref} {commit}\nprepare\ncommit\n".encode()
        input_file = stage_root / "integration-ref.stdin"
        _write_private(input_file, payload)
        record["native_plan"] = {"argv": _git_argv("update-ref", "--stdin", "--no-deref"),
                                 "cwd": str(repo), "env": env, "stdin": self.core.reference(input_file)}
        with _integration_lock(repo, record["guard"]) as guard_fd:
            stage["import_plan"] = self._plan_object_import(repo, stage)

            def guard(current):
                self._phase(current, request, attempt)
                self._validate_stage(repo, attempt, record, env)

            intent = self._append(state, "worker_admission_intent", request, record, guard)
            return self._apply_admission(state, request, attempt, intent, env, guard_fd)

    def _validate_retained_stage(self, repo, attempt, record, env):
        stage = record["stage"]
        root = Path(stage["root"]["path"])
        scratch = root / "receiver-scratch"
        self._storage_identity(attempt)
        if (_directory(root) != stage["root"] or _directory(scratch) != stage["receiver_scratch"]
                or _toolchain(repo, scratch) != attempt["toolchain"]):
            raise WorkerHold("staged admission storage or toolchain changed")
        quarantine = root / "quarantine.git"
        metadata = _git_metadata(quarantine, saved=stage["quarantine"], bare=True)
        binding = stage["binding"]
        if (executable(root / "fixed-relay") != binding["relay"] or binding["relay_parent"] != stage["root"]
                or binding["quarantine"] != metadata["directory"] or binding["toolchain"] != attempt["toolchain"]
                or binding["source"] != _directory(Path(attempt["root"]) / ".git")):
            raise WorkerHold("fixed transport relay or repository identity changed")
        for receipt in (stage["source_qualification"], stage["receiver_qualification"], stage["strict_objects"],
                        *stage["transport"].values(), *stage["protocol_streams"].values(),
                        record["native_plan"]["stdin"]):
            self.core.verify_reference(receipt)
        if _inventory(quarantine / "objects") != stage["objects"]:
            raise WorkerHold("strictly received Git objects changed before consumption")
        if (stage["commit"] != record["commit"]
                or _raw_commit(quarantine, record["commit"], record["predecessor"]["commit"], env) != stage["tree"]):
            raise WorkerHold("quarantined literal commit identity changed")
        ref = _git_ok(_run(_git_argv("rev-parse", "--verify", "refs/quarantine/submitted"), quarantine, env),
                      "recheck the pinned quarantine ref")
        if ref != record["commit"].encode() + b"\n":
            raise WorkerHold("pinned quarantine ref changed after validation")

    def _validate_stage(self, repo, attempt, record, env):
        stage = record["stage"]
        self._validate_retained_stage(repo, attempt, record, env)
        if self._integrated(repo, attempt, env) != record["before"]:
            raise ValueError("integration source, modes or refs changed before admission")
        _reserved_ref_absent(repo, record["ref"], record["before"]["refs"])
        if self._plan_object_import(repo, stage) != stage["import_plan"]:
            raise WorkerHold("guarded object import plan changed before admission")
        for name, change in stage["changes"].items():
            if self.contract.path_identity(repo, name, self.core) != change["before_identity"]:
                raise ValueError("integration changed a planned path's physical identity")
            if change["file"] is not None:
                self.core.verify_reference(change["file"])
                if stat.S_IMODE(Path(change["file"]["path"]).lstat().st_mode) != change["after"]["mode"]:
                    raise ValueError("staged file mode changed before integration")

    def _import_objects(self, repo, stage):
        root = Path(stage["root"]["path"])
        destination = repo / ".git" / "objects"
        plan = stage["import_plan"]
        directories = dict(plan["before"]["directories"])
        device = directories["."]["device"]
        if _object_effect(repo, plan["sources"], len(stage["commit"])) != plan["before"]:
            raise WorkerHold("affected object state changed before controller import")
        for name, row in directories.items():
            if row is not None:
                continue
            if _object_directory(destination, device) != directories["."]:
                raise WorkerHold("integration object store root changed before directory creation")
            folder = destination / name
            folder.mkdir(mode=0o755)
            fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                info = os.fstat(fd)
                if info.st_dev != device:
                    raise WorkerHold("new object directory is on an unqualified volume")
                os.fchmod(fd, plan["after"]["directories"][name]["mode"])
                os.fsync(fd)
                observed = _object_directory(folder, device)
                if observed["inode"] != info.st_ino:
                    raise WorkerHold("new object directory identity changed before import")
                directories[name] = observed
            finally:
                os.close(fd)
            self.core._sync_directory(destination)
        # Install pack data before the index that makes it visible to Git.
        for name in sorted(plan["sources"], key=lambda item: (item.endswith(".idx"), item)):
            source = root / "import" / _sha(name.encode())
            target = destination / name
            parent = target.parent
            if (_directory(root / "import") != stage["import_storage"]
                    or _object_file(source, device) != plan["sources"][name]
                    or _object_directory(destination, device) != directories["."]
                    or _object_directory(parent, device) != directories[parent.name]):
                raise WorkerHold("staged raw import or its destination identity changed")
            exists = target.name in _object_entries(parent, (target.name,))
            existing = _object_file(target, device) if exists else None
            if existing != plan["before"]["files"][name]:
                raise WorkerHold("affected Git object changed before its import")
            if existing is not None:
                continue
            os.replace(source, target)
            self.core._sync_directory(parent)

    def _apply_files(self, repo, stage):
        for name, change in stage["changes"].items():
            identity = change["before_identity"]
            if self.contract.path_identity(repo, name, self.core) != identity:
                raise ValueError("physical integration path changed before file application")
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            with contextlib.ExitStack() as handles:
                fd = os.open(repo, flags)
                handles.callback(os.close, fd)
                for ancestor in identity["ancestors"]:
                    if ancestor["path"] != ".":
                        fd = os.open(Path(ancestor["path"]).name, flags, dir_fd=fd)
                        handles.callback(os.close, fd)
                    info = os.fstat(fd)
                    if (info.st_dev, info.st_ino) != (ancestor["device"], ancestor["inode"]):
                        raise ValueError("integration parent descriptor differs from the planned path")
                leaf = Path(name).name
                if change["file"] is None:
                    os.unlink(leaf, dir_fd=fd)
                else:
                    self.core.verify_reference(change["file"])
                    os.replace(change["file"]["path"], leaf, dst_dir_fd=fd)
                os.fsync(fd)

    def _admission_outcome(self, actual, record):
        if actual is None:
            return "UNKNOWN"
        before, after = record["before"], record["after"]
        plan = record["stage"]["import_plan"]
        if actual == dict(before, objects=plan["before"]):
            return "NO_EFFECT"
        objects = actual["objects"]
        before_files = before["inventory"]["files"]
        after_files = after["inventory"]["files"]
        actual_files = actual["inventory"]["files"]
        if (actual["refs"] not in (before["refs"], after["refs"])
                or actual["inventory"]["directories"] != before["inventory"]["directories"]
                or any(actual_files.get(name) not in (before_files.get(name), after_files.get(name))
                       for name in before_files.keys() | after_files.keys() | actual_files.keys())):
            return "UNKNOWN"
        intended_objects = True
        for kind, slots in objects.items():
            for name, observed in slots.items():
                if _matches_object_slot(observed, plan["after"][kind][name]):
                    continue
                intended_objects = False
                if observed != plan["before"][kind][name]:
                    return "UNKNOWN"
        if intended_objects and actual["refs"] == after["refs"] and actual["inventory"] == after["inventory"]:
            return "INTENDED"
        return "PARTIAL"

    def _save_admission_result(self, conn, state, request, intent, actual, error, native):
        record = intent["data"]
        outcome = self._admission_outcome(actual, record)
        data = {"attempt": record["attempt"], "intent": intent["id"], "commit": record["commit"], "ref": record["ref"],
                "outcome": outcome, "actual": actual, "error": error, "native_ref": native}
        self.ledger._insert_event(conn, state, self._event("worker_admission_result", request, data))
        conn.commit()
        return self._admission_response(record, data)

    def _admission_response(self, record, result):
        outcome = result["outcome"]
        status = {"INTENDED": "PASS", "NO_EFFECT": "BLOCK"}.get(outcome, "HOLD")
        return {"state": status, "outcome": outcome,
                "errors": [] if status == "PASS" else [result["error"] or "admission integration state is " + outcome],
                "admission": {"commit": record["commit"], "ref": record["ref"], "tree": record["stage"]["tree"],
                              "source_qualification": record["stage"]["source_qualification"],
                              "receiver_qualification": record["stage"]["receiver_qualification"],
                              "transport": record["stage"]["transport"], "native_ref": result["native_ref"]}}

    def _apply_admission(self, state, request, attempt, intent, env, guard_fd):
        record = intent["data"]
        repo, root = Path(state["contract"]["repo"]), Path(record["stage"]["root"]["path"])
        native, error, actual = None, None, None
        with self.ledger._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = self.ledger._read(conn, state["contract"]["run_id"])
            if current["sha256"] != intent["sha256"]:
                raise WorkerHold("admission prefix advanced after durable intent; reconcile original request")
            self._phase(current, request, attempt, own_intent=intent["id"])
            self._validate_stage(repo, attempt, record, env)
            native_plan = record["native_plan"]
            self.core.verify_reference(native_plan["stdin"])
            payload = _read_regular(Path(native_plan["stdin"]["path"]))
            try:
                self._import_objects(repo, record["stage"])
                result = _run(native_plan["argv"], repo, env, data=payload, fds=(guard_fd,))
                native = self._receipt(root, "integration-ref", result)
                if result["timed_out"]:
                    raise WorkerHold("native integration writer timed out; restart must acquire the retained guard", native)
                _git_ok(result, "compare-and-swap the exact integration ref")
                self._apply_files(repo, record["stage"])
            except WorkerHold as exc:
                if exc.receipt is not None:
                    raise
                error = str(exc)
            except (self.core.RuntimeError, ValueError, OSError) as exc:
                error = str(exc)
            try:
                actual = self._integrated(repo, attempt, env, record["stage"])
            except (self.core.RuntimeError, ValueError, OSError) as exc:
                error = str(exc)
            return self._save_admission_result(conn, current, request, intent, actual, error, native)

    def _reconcile(self, state, expected_seq, request, intent):
        record = intent["data"]
        if record["request"] != request or record["expected_seq"] != expected_seq:
            raise ValueError("retry must match the original immutable admission request and sequence")
        if "import_plan" not in record["stage"]:
            raise WorkerHold("recorded admission lacks its complete affected object projection")
        repo = Path(state["contract"]["repo"])
        with _integration_lock(repo, record["guard"]), self.ledger._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = self.ledger._read(conn, state["contract"]["run_id"])
            if (self._by_request(current, "worker_admission_intent", request) != intent
                    or intent["seq"] != expected_seq + 1):
                raise WorkerHold("admission intent or original sequence changed before recovery")
            prefix = dict(current, events=current["events"][:expected_seq],
                          seq=expected_seq, sha256=intent["previous_sha256"])
            attempt = self._attempt(prefix, request)
            submitted = self._recent(prefix, "worker_submission", attempt)
            if (attempt != self._attempt(current, request) or record["attempt"] != attempt["id"]
                    or record["guard"] != attempt["integration"]["directory"]
                    or record["phase"] != attempt["phase"] or record["predecessor"] != attempt["predecessor"]
                    or record["ref"] != attempt["integration_ref"]
                    or submitted is None or submitted["id"] != record["submission"]
                    or submitted["data"]["id"] != request["submission"]
                    or submitted["data"]["commit"] != record["commit"]):
                raise WorkerHold("admission recovery lost its exact attempt or submission binding")
            saved = self._by_request(current, "worker_admission_result", request)
            if saved is not None and self.runtime.admission_resolved(saved):
                self._phase(current, request, attempt, own_intent=intent["id"], reconciling=True)
            root = Path(record["stage"]["root"]["path"])
            env = _git_env(root / "receiver-scratch", helpers=attempt["toolchain"]["helpers"])
            try:
                self._validate_retained_stage(repo, attempt, record, env)
            except (self.core.RuntimeError, ValueError, OSError) as exc:
                raise WorkerHold("admission recovery could not verify retained identities: " + str(exc)) from exc
            error, actual = None, None
            try:
                actual = self._integrated(repo, attempt, env, record["stage"])
            except (self.core.RuntimeError, ValueError, OSError) as exc:
                error = str(exc)
            if saved is not None:
                if actual is None:
                    raise WorkerHold("admission recovery could not verify the saved projection: " + (error or "unavailable"))
                if (saved["data"]["actual"] != actual or saved["data"]["intent"] != intent["id"]
                        or any(saved["data"][name] != record[name] for name in ("attempt", "commit", "ref"))):
                    raise WorkerHold("recorded admission no longer matches actual source, modes, refs and objects")
                return self._admission_response(record, saved["data"])
            # A pending intent can be observed after retirement. This transaction writes only its readback.
            return self._save_admission_result(conn, current, request, intent, actual, error, None)

    def _cleanup(self, state, request):
        attempt = self._attempt(state, request)
        if self._recent(state, "worker_dispatch_intent", attempt):
            raise WorkerHold("possible worker or descendant requires clone and evidence retention")
        self.runtime.require_resolved_admissions(state)
        if self._recent(state, "worker_cleanup_intent", attempt):
            raise WorkerHold("cleanup already has a durable intent; preserve remaining evidence")
        if request["retained_commit"] != attempt["predecessor"]["commit"]:
            raise WorkerHold("cleanup requires retention of the exact generation commit")
        self._storage_identity(attempt)
        root, scratch = Path(attempt["root"]), Path(attempt["scratch"])
        inventory = _inventory(root)
        if (self.core.digest(inventory) != attempt["inventory"] or any(scratch.iterdir())
                or not shutil.rmtree.avoids_symlink_attacks):
            raise WorkerHold("clone has unaccounted evidence or no qualified physical removal path")
        repo = Path(state["contract"]["repo"])
        toolchain = self._prepared_toolchain(attempt, repo)
        env = _git_env(scratch, helpers=toolchain["helpers"])
        with _integration_lock(repo, attempt["integration"]["directory"]):
            _git_metadata(repo, saved=attempt["integration"])
            retention = _retaining_ref(repo, env, attempt["predecessor"])
            directory = self._storage(state, "cleanup-")
            accounting = directory / "file-inventory.json"
            _write_private(accounting, self.core.canonical(inventory))
            data = {"attempt": attempt["id"], "root": attempt["root_identity"], "commit": request["retained_commit"],
                    "accounting": self.core.reference(accounting), "retention": retention}
            intent = self._append(state, "worker_cleanup_intent", request, data)
            with self.ledger._connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                current = self.ledger._read(conn, state["contract"]["run_id"])
                if (current["sha256"] != intent["sha256"] or self._recent(current, "worker_dispatch_intent", attempt)
                        or _inventory(root) != inventory or any(scratch.iterdir())):
                    raise WorkerHold("disposable clone no longer has complete never-dispatched accounting")
                self.runtime.require_resolved_admissions(current)
                self._storage_identity(attempt)
                self._authority(current, "cleanup")
                _git_metadata(repo, saved=attempt["integration"])
                if _retaining_ref(repo, env, attempt["predecessor"], retention["ref"]) != retention:
                    raise WorkerHold("cleanup retaining ref changed before removal")
                shutil.rmtree(root)
                self.core._sync_directory(root.parent)
                reclaimed = sum(row["size"] for row in inventory["files"].values())
                result = {"attempt": attempt["id"], "intent": intent["id"], "reclaimed_bytes": reclaimed}
                self.ledger._insert_event(conn, current, self._event("worker_cleanup_result", request, result))
                conn.commit()
        return {"state": "PASS", "errors": [], "reclaimed_bytes": reclaimed}

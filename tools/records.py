"""Read the property and rule format shared by the three I2E skills."""
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date

KINDS = {"properties": "property", "rules": "rule"}
PREFIX = {"property": "prop-", "rule": "rule-"}
TYPES = {"property": {"round-trip", "invariant", "idempotency", "equivalence", "other"},
         "rule": {"review", "blind-spot", "test", "hook", "instruction"}}
SECTIONS = {"property": ("Statement",), "rule": ("Trigger", "Check", "Why it flags")}
FIELDS = ("id", "kind", "type", "status", "tags", "applies-to", "seen-in", "updated")
PRIVATE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\bAKIA[0-9A-Z]{16}\b|\bgh[pousr]_[A-Za-z0-9]{30,}|"
    r"\bgithub_pat_[A-Za-z0-9_]{20,}|\bsk-[A-Za-z0-9_-]{20,}|\bxox[abprs]-[A-Za-z0-9-]{10,}|"
    r"\b(?:password|passwd|secret|api[_-]?key|access[_-]?token)\s*[:=]\s*\S+|"
    r"/(?:Users|home)/[^/\s]+/|[A-Z]:\\Users\\|https?://[^/\s]+@|"
    r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", re.IGNORECASE)
LIMIT = 64 * 1024


def normalized(value):
    return " ".join(value.casefold().split())


@dataclass
class Entry:
    fields: dict
    body: str

    def bytes(self):
        header = "\n".join(f"{name}: {self.fields[name]}" for name in FIELDS)
        return ("---\n" + header + "\n---\n" + self.body).encode()

    def section(self, title):
        parts = re.split(r"(?m)^##[ \t]+(.+?)[ \t]*$", self.body)
        sections = dict(zip(parts[1::2], parts[2::2]))
        return sections.get(title, "").strip()

    def key(self):
        kind = self.fields["kind"]
        scope = tuple(sorted(normalized(s) for s in self.fields["applies-to"].split(",")))
        return (kind, scope, tuple(normalized(self.section(t)) for t in SECTIONS[kind][:2]))


def read_entry(name, raw):
    folder, leaf = name.split("/", 1)
    kind = KINDS[folder]
    if len(raw) > LIMIT:
        raise ValueError(f"{name}: entry exceeds 64 KiB")
    text = raw.decode("utf-8").replace("\r\n", "\n")
    if PRIVATE.search(text) or any(ord(c) < 32 and c not in "\n\t" for c in text):
        raise ValueError(f"{name}: review private-looking or non-text content")
    match = re.fullmatch(r"---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if not match:
        raise ValueError(f"{name}: missing Markdown front matter")
    fields = {}
    for line in match[1].splitlines():
        key, sep, val = line.partition(":")
        if not sep or key in fields or not val.strip():
            raise ValueError(f"{name}: invalid front matter")
        fields[key] = val.strip()
    if set(fields) != set(FIELDS):
        raise ValueError(f"{name}: missing or unexpected fields")
    entry_id = fields["id"]
    if (not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", entry_id) or not entry_id.startswith(PREFIX[kind])
            or leaf != entry_id + ".md" or len(entry_id) > 160 or fields["kind"] != kind):
        raise ValueError(f"{name}: ID, name and kind must match")
    if fields["type"] not in TYPES[kind] or fields["status"] not in {"candidate", "adopted", "retired"}:
        raise ValueError(f"{name}: unknown type or status")
    for key in ("tags", "applies-to", "seen-in"):
        items = [normalized(i) for i in fields[key].split(",")]
        if not all(items) or any(n > 1 for n in Counter(items).values()):
            raise ValueError(f"{name}: {key} must contain distinct, nonempty items")
    if kind == "rule" and fields["status"] == "adopted" and len(fields["seen-in"].split(",")) < 2:
        raise ValueError(f"{name}: adopted rules require two distinct observed changes")
    if date.fromisoformat(fields["updated"]).isoformat() != fields["updated"]:
        raise ValueError(f"{name}: invalid YYYY-MM-DD date")
    entry = Entry(fields, match[2].rstrip() + "\n")
    if any(not entry.section(title) for title in SECTIONS[kind]):
        raise ValueError(f"{name}: required sections must explain the actual statement or check")
    return entry


def draft_entries(root):
    if root.is_symlink() or not root.is_dir():
        raise ValueError("select an existing private reflection draft directory")
    result = {}
    for directory in root.iterdir():
        if directory.name not in KINDS or directory.is_symlink() or not directory.is_dir():
            raise ValueError("drafts may contain only properties/ and rules/")
        for path in directory.iterdir():
            if (path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1
                    or path.suffix != ".md" or path.name == "README.md" or path.stat().st_size > LIMIT):
                raise ValueError(f"invalid draft path in {directory.name}/")
            name = f"{directory.name}/{path.name}"
            result[name] = read_entry(name, path.read_bytes())
    return result


def reconcile(existing, drafts):
    """Merge independent sightings. Preserve curated status, scope, wording and retirements."""
    changes = {}
    keys = {entry.key(): name for name, entry in existing.items()}
    for name, proposal in sorted(drafts.items()):
        old = existing.get(name)
        if not old:
            if proposal.fields["status"] != "candidate":
                raise ValueError(f"{name}: submit new findings as candidates")
            if proposal.key() in keys:
                raise ValueError(f"{name}: this definition already exists at {keys[proposal.key()]}")
            keys[proposal.key()] = name
            changes[name] = proposal.bytes()
            continue
        excluded = {"seen-in", "updated", "status"}
        if (any(old.fields[k] != proposal.fields[k] for k in FIELDS if k not in excluded)
                or old.body != proposal.body):
            raise ValueError(f"{name}: definition changed; reconcile the draft against latest main")
        seen = [s.strip() for s in old.fields["seen-in"].split(",")]
        known = {normalized(v) for v in seen}
        extra = [s.strip() for s in proposal.fields["seen-in"].split(",") if normalized(s) not in known]
        if extra:
            values = dict(old.fields)
            values["seen-in"] = ", ".join(seen + extra)
            values["updated"] = max(values["updated"], proposal.fields["updated"])
            changes[name] = Entry(values, old.body).bytes()
    return changes

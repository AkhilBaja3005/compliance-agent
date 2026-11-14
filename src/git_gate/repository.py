"""Read bare Git repositories and receive-pack quarantine without checkout."""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
MAX_FILES = 10_000
MAX_BLOB_BYTES = 4 * 1024 * 1024
MAX_TREE_BYTES = 64 * 1024 * 1024
MAX_COMMITS = 100


@dataclass(frozen=True)
class RefUpdate:
    old: str
    new: str
    ref: str

    @property
    def deleted(self) -> bool:
        return set(self.new) == {"0"}

    @property
    def created(self) -> bool:
        return set(self.old) == {"0"}


def parse_updates(text: str) -> list[RefUpdate]:
    updates = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 3 or not all(OID.fullmatch(s) for s in fields[:2]):
            raise ValueError("Invalid Git ref-update input")
        old, new, ref = fields
        if len(old) != len(new) or not ref.startswith(("refs/heads/", "refs/tags/")):
            raise ValueError("Only branch and commit-tag updates are supported")
        if any(u.ref == ref for u in updates):
            raise ValueError("Duplicate ref update")
        update = RefUpdate(old, new, ref)
        if ref == "refs/heads/main" and update.deleted:
            raise ValueError("Cannot delete the canonical main branch")
        updates.append(update)
    if not updates:
        raise ValueError("No ref updates received")
    return updates


class Repository:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.env = {k: v for k, v in os.environ.items() if k in {
            "PATH", "LANG", "LC_ALL", "TMPDIR", "GIT_OBJECT_DIRECTORY",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_QUARANTINE_PATH"}}
        self.env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null", GIT_TERMINAL_PROMPT="0")
        if self.git("rev-parse", "--is-bare-repository").strip() != b"true":
            raise ValueError("Gate requires a bare repository")

    def git(self, *args: str) -> bytes:
        result = subprocess.run(["git", "--no-replace-objects", "--git-dir", str(self.path), *args],
                                env=self.env, capture_output=True, check=False)
        if result.returncode:
            raise ValueError(f"Git {args[0]} failed")
        return result.stdout

    def commit(self, revision: str) -> str:
        return self.git("rev-parse", "--verify", f"{revision}^{{commit}}").decode().strip()

    def comparisons(self, updates: list[RefUpdate]) -> list[tuple[str | None, str]]:
        existing = self.git("for-each-ref", "--format=%(objectname)").decode().splitlines()
        pairs: list[tuple[str | None, str]] = []
        tips = []
        for update in updates:
            self.git("check-ref-format", update.ref)
            current = self.git("for-each-ref", "--format=%(objectname)", update.ref).decode().splitlines()
            actual = current[0] if current else "0" * len(update.old)
            if actual != update.old:
                raise ValueError("Ref changed while preparing push; retry")
            if update.deleted:
                continue
            tip = self.commit(update.new)
            base = self.commit("refs/heads/main") if update.created else self.commit(update.old)
            pairs.append((base, tip))
            tips.append(tip)
        if tips:
            revisions = "\n".join(tips + ["^" + oid for oid in existing]) + "\n"
            result = subprocess.run(["git", "--no-replace-objects", "--git-dir", str(self.path),
                                     "rev-list", "--reverse", "--topo-order", f"--max-count={MAX_COMMITS + 1}", "--stdin"],
                                    input=revisions.encode(), env=self.env, capture_output=True)
            if result.returncode:
                raise ValueError("Cannot enumerate incoming commits")
            commits = result.stdout.decode().splitlines()
            if len(commits) > MAX_COMMITS:
                raise ValueError(f"Push exceeds {MAX_COMMITS} incoming commits")
            for commit in commits:
                row = self.git("rev-list", "--parents", "-n", "1", commit).decode().split()
                pairs.append((row[1] if len(row) > 1 else None, commit))
        return list(dict.fromkeys(pairs))

    def materialize(self, commit: str, root: Path) -> None:
        rows = self.git("ls-tree", "-rlz", "--full-tree", commit).split(b"\0")
        files = []
        total = 0
        for row in filter(None, rows):
            meta, raw_path = row.split(b"\t", 1)
            mode, kind, oid, size = meta.split()
            path = raw_path.decode("utf-8")
            parts = PurePosixPath(path).parts
            if (not parts or path.startswith("/") or "\\" in path or
                    any(p in {".", ".."} or p.casefold() == ".git" for p in parts) or
                    any(ord(c) < 32 or ord(c) == 127 for c in path)):
                raise ValueError("Unsupported path in commit tree")
            if kind != b"blob" or mode not in {b"100644", b"100755"}:
                raise ValueError("Symlinks and submodules are not supported in scanned snapshots")
            length = int(size)
            total += length
            if length > MAX_BLOB_BYTES or total > MAX_TREE_BYTES or len(files) >= MAX_FILES:
                raise ValueError("Commit snapshot exceeds scanner limits")
            files.append((path, oid.decode()))
        for path, oid in files:
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.git("cat-file", "blob", oid))

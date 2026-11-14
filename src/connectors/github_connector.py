"""GitHub connector: local directory or live repo URL -> ASTSlice + BehavioralCapabilityCard (+ deps) with commit SHA."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from src.edge_extractors.code_scanner import ScanResult, scan_code
from src.schemas.artifacts import sha256_text

GITHUB_URL_RE = re.compile(r"^(https://github\.com/[\w.\-]+/[\w.\-]+?)(\.git)?/?$")


@dataclass
class GitHubScan:
    result: ScanResult
    origin: str  # "local:<path>" | "github:<url>"
    commit_sha: str
    cloned: bool = False


def is_github_url(source: str) -> bool:
    return bool(GITHUB_URL_RE.match(str(source).strip()))


def _git(args: list[str], cwd: Path | None = None, env: dict | None = None, timeout: int = 180) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    if out.returncode != 0:
        # never echo env/token material; stderr from git does not contain extraheader values
        raise RuntimeError(f"git {args[0]} failed: {out.stderr.strip()[:300]}")
    return out.stdout.strip()


def local_commit_sha(path: Path) -> str:
    """HEAD SHA if `path` is inside a git work tree whose root *is* that path; else a deterministic tree hash."""
    try:
        top = Path(_git(["rev-parse", "--show-toplevel"], cwd=path)).resolve()
        if top == path.resolve():
            return _git(["rev-parse", "HEAD"], cwd=path)
    except Exception:
        pass
    files = sorted(p.relative_to(path).as_posix() + ":" + sha256_text(p.read_text(encoding="utf-8", errors="replace"))
                   for p in path.rglob("*") if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts)
    return "local-" + sha256_text("\n".join(files))[:40]


@contextmanager
def shallow_clone(url: str, token: str | None = None):
    """Shallow-clone into a temp dir (token via git config env, never argv/URL); deleted on exit."""
    tmp = tempfile.mkdtemp(prefix="aegis_clone_")
    try:
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
        if token:
            import base64

            basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
            env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
                       GIT_CONFIG_VALUE_0=f"AUTHORIZATION: basic {basic}")
        dest = Path(tmp) / "repo"
        _git(["clone", "--depth", "1", "--quiet", url if url.endswith(".git") else url + ".git", str(dest)], env=env)
        yield dest
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def scan_github_source(source: str | Path, tenant_id: str, token: str | None = None) -> GitHubScan:
    """`source` is a local directory (e.g. ./sample_connectors/github/...) or https://github.com/org/repo."""
    src = str(source).strip()
    token = token or os.getenv("GITHUB_TOKEN") or None
    if is_github_url(src):
        url = GITHUB_URL_RE.match(src).group(1)
        with shallow_clone(url, token) as repo:  # temp folder removed after scanning
            sha = _git(["rev-parse", "HEAD"], cwd=repo)
            result = scan_code(repo, tenant_id)
            _stamp(result, sha, f"github:{url}")
            return GitHubScan(result, f"github:{url}", sha, cloned=True)
    path = Path(src)
    if not path.is_dir():
        raise FileNotFoundError(f"GitHub source not found: {src}")
    sha = local_commit_sha(path)
    result = scan_code(path, tenant_id)
    _stamp(result, sha, f"local:{path}")
    return GitHubScan(result, f"local:{path}", sha)


def _stamp(result: ScanResult, sha: str, origin: str) -> None:
    for s in result.slices:
        s.commit_sha, s.origin = sha, origin
    for c in result.cards:
        c.commit_sha = sha

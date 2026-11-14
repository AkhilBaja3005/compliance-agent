"""Bounded pre-receive supervisor and post-receive acceptance journal."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

from .policy import Policy
from .repository import parse_updates


def supervise(policy_path: Path, input_text: str, timeout: int) -> dict:
    # Do not inherit provider credentials, tracing configuration, PYTHONPATH or Git config injection.
    env = {k: v for k, v in os.environ.items() if k in {
        "PATH", "LANG", "LC_ALL", "TMPDIR", "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_QUARANTINE_PATH"}}
    env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
    root = Path(__file__).resolve().parents[2]
    child = subprocess.Popen([sys.executable, "-m", "src.git_gate.worker", "--policy", str(policy_path)],
                             cwd=root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        stdout, _ = child.communicate(input_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
        child.communicate()
        return {"decision": "ERROR", "error": f"Scanner exceeded {timeout} second push deadline"}
    if child.returncode:
        return {"decision": "ERROR", "error": "Scanner process failed"}
    try:
        result = json.loads(stdout)
        if result.get("decision") not in {"ALLOW", "BLOCK", "ERROR"}:
            raise ValueError("Invalid scanner decision")
        if result["decision"] != "ERROR":
            if (result.get("updates") != [asdict(u) for u in parse_updates(input_text)] or
                    result.get("policy_sha256") != Policy.load(policy_path).checksum or
                    not isinstance(result.get("snapshots"), dict) or
                    not isinstance(result.get("comparisons"), list) or
                    not isinstance(result.get("regressions"), list) or
                    bool(result["regressions"]) != (result["decision"] == "BLOCK")):
                raise ValueError("Incomplete scanner decision")
        return result
    except (ValueError, AttributeError, TypeError):
        return {"decision": "ERROR", "error": "Scanner returned an invalid decision"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Aegis Git receive hook")
    parser.add_argument("--git-dir", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--reports", type=Path, required=True)
    parser.add_argument("--post-receive", action="store_true")
    args = parser.parse_args()
    started = time.monotonic()
    input_text = sys.stdin.read(1024 * 1024 + 1)
    token = os.environ.get("GRAPHITE_PUSH_ID", "")
    if not re.fullmatch(r"[0-9a-f]{32}", token):
        token = hashlib.sha256(f"{os.getppid()}:{input_text}".encode()).hexdigest()[:32]
    result = {"push_id": token, "recorded_at": datetime.now(timezone.utc).isoformat()}
    try:
        if len(input_text) > 1024 * 1024:
            raise ValueError("Too many ref updates")
        policy = Policy.load(args.policy.resolve())
        if args.git_dir.resolve() != Path(policy.repository).resolve():
            raise ValueError("Repository does not match administrator policy")
        updates = parse_updates(input_text)
        if args.post_receive:
            result.update(decision="ACCEPTED", updates=[asdict(u) for u in updates])
        else:
            result.update(supervise(args.policy.resolve(), input_text, policy.timeout_seconds))
            result.setdefault("policy_sha256", policy.checksum)
    except Exception as exc:
        result.update(decision="ERROR", error=f"{type(exc).__name__}: {exc}")
    result["duration_seconds"] = round(time.monotonic() - started, 3)
    suffix = ".accepted.json" if args.post_receive else ".json"
    try:
        args.reports.mkdir(parents=True, exist_ok=True)
        destination = args.reports / (token + suffix)
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(destination)
    except OSError:
        print("GRAPHITE ERROR: cannot persist the push decision", file=sys.stderr)
        return 2
    decision = result["decision"]
    print(f"GRAPHITE {decision}: report {token}{suffix}", file=sys.stderr)
    for regression in result.get("regressions", []):
        print(f"  {regression['commit'][:12]} {regression['check_id']} "
              f"{regression['exact_locator']} ({regression['qualified_name']})", file=sys.stderr)
        steps = regression["finding"].get("remediation_steps", [])
        if steps:
            print(f"    Fix: {steps[0]}", file=sys.stderr)
    warnings = sum(len(s[category]) for s in result.get("snapshots", {}).values()
                   for category in ("suspected_gaps", "quarantined_for_human_review"))
    if warnings:
        print(f"  {warnings} advisory/uncertain finding(s) retained in the report", file=sys.stderr)
    if result.get("error"):
        # Escape control characters from filenames or parser errors before terminal display.
        print("  " + ascii(result["error"]), file=sys.stderr)
    return {"ALLOW": 0, "ACCEPTED": 0, "BLOCK": 1, "ERROR": 2}[decision]


if __name__ == "__main__":
    raise SystemExit(main())

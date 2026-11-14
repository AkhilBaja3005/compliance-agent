"""Runs inside a supervised process; stdout is one JSON decision."""
from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import asdict
from pathlib import Path
import sys

from .evaluator import SCANNER_VERSION, SnapshotAuditor
from .policy import Policy
from .repository import Repository, parse_updates


def evaluate_push(policy: Policy, input_text: str) -> dict:
    repo = Repository(Path(policy.repository))
    updates = parse_updates(input_text)
    pairs = repo.comparisons(updates)
    auditor = SnapshotAuditor(policy)
    cache = {}
    comparisons, regressions = [], []

    def snapshot(commit):
        if commit not in cache:
            with tempfile.TemporaryDirectory(prefix="aegis_snapshot_") as tmp:
                root = Path(tmp)
                if commit:
                    repo.materialize(commit, root)
                cache[commit] = auditor.evaluate(root, commit)
        return cache[commit]

    for baseline, candidate in pairs:
        before, after = snapshot(baseline), snapshot(candidate)
        added = sorted(after.confirmed.keys() - before.confirmed.keys())
        comparisons.append({"baseline": baseline, "candidate": candidate, "new_instances": added})
        for instance in added:
            regressions.append({"commit": candidate, "baseline": baseline,
                                "instance_id": instance, **after.confirmed[instance]})
    return {"decision": "BLOCK" if regressions else "ALLOW", "scanner_version": SCANNER_VERSION,
            "policy_sha256": policy.checksum, "rule_library_version": auditor.laws.version,
            "updates": [asdict(u) for u in updates], "comparisons": comparisons,
            "regressions": regressions,
            "snapshots": {sha or "empty": result.report.model_dump(mode="json") for sha, result in cache.items()}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = evaluate_push(Policy.load(args.policy), sys.stdin.read())
    except Exception as exc:
        result = {"decision": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(result))


if __name__ == "__main__":
    main()

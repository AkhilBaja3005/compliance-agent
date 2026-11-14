"""Evaluation harness: score audit findings against gold labels (precision / recall per check and overall).

Positive = CONFIRMED_VIOLATION. A `confirmed` check that is not confirmed is a false negative; a confirmed check listed in
`not_confirmed` (or any confirmed check when `expect_none`) is a false positive; `known_missed` entries are planted defects the
tool has no check for and always count as false negatives. Numbers reflect only the gold set they are computed on.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_GOLD = Path(__file__).resolve().parent.parent / "tests" / "eval" / "gold.json"


@dataclass
class CaseResult:
    name: str
    tp: list[str] = field(default_factory=list)
    fp: list[str] = field(default_factory=list)
    fn: list[str] = field(default_factory=list)
    tn: int = 0
    known_missed: list[str] = field(default_factory=list)


def _rate(num: int, den: int) -> float | None:
    return round(num / den, 3) if den else None


def evaluate(gold_path: Path | str = DEFAULT_GOLD, frameworks: str = "EU_AI_ACT,EU_GDPR", root: Path | None = None, run=None) -> dict:
    import os

    from src.agents import run_audit

    run = run or run_audit
    root = root or Path(gold_path).resolve().parent.parent.parent
    gold = json.loads(Path(gold_path).read_text())
    prev = os.environ.get("AEGIS_FRAMEWORKS")
    os.environ["AEGIS_FRAMEWORKS"] = frameworks
    cases: list[CaseResult] = []
    per_check: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    try:
        for c in gold["cases"]:
            os.environ["AEGIS_FRAMEWORKS"] = c.get("frameworks", frameworks)  # a case may need another scope (e.g. EU data-residency checks)
            rep = run(root / c["path"], c["name"])
            confirmed = {f.check_id for f in rep.confirmed_findings if f.check_id}
            res = CaseResult(c["name"])
            want = set(c.get("confirmed", []))
            forbid = set(c.get("not_confirmed", [])) | (confirmed if c.get("expect_none") else set())
            for k in sorted(want):
                (res.tp if k in confirmed else res.fn).append(k)
                per_check[k]["tp" if k in confirmed else "fn"] += 1
            for k in sorted(forbid & confirmed):
                res.fp.append(k)
                per_check[k]["fp"] += 1
            res.tn = len(forbid - confirmed)
            res.known_missed = list(c.get("known_missed", []))
            for m in res.known_missed:
                per_check[m.split(" ")[0]]["fn"] += 1
            cases.append(res)
    finally:
        if prev is None:
            os.environ.pop("AEGIS_FRAMEWORKS", None)
        else:
            os.environ["AEGIS_FRAMEWORKS"] = prev
    tp = sum(len(c.tp) for c in cases)
    fp = sum(len(c.fp) for c in cases)
    fn = sum(len(c.fn) + len(c.known_missed) for c in cases)
    return {
        "frameworks": frameworks, "cases": [vars(c) for c in cases],
        "per_check": {k: {**v, "precision": _rate(v["tp"], v["tp"] + v["fp"]), "recall": _rate(v["tp"], v["tp"] + v["fn"])} for k, v in sorted(per_check.items())},
        "overall": {"tp": tp, "fp": fp, "fn": fn, "precision": _rate(tp, tp + fp), "recall": _rate(tp, tp + fn),
                    "recall_excluding_known_missed": _rate(tp, tp + sum(len(c.fn) for c in cases))},
        "caveat": "Gold set is small and synthetic; the numbers describe this set only.",
    }

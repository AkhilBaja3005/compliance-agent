"""CI gate: planted defects must stay detected and clean cases must stay clean (EU AI Act scope)."""
from __future__ import annotations

from src.evaluation import evaluate


def test_recall_and_precision_gate():
    res = evaluate()
    o = res["overall"]
    assert o["recall_excluding_known_missed"] == 1.0, [c for c in res["cases"] if c["fn"]]
    assert o["precision"] == 1.0, [c for c in res["cases"] if c["fp"]]
    # known-missed defects are counted as false negatives, so recall can only be 1.0 when none are listed in the gold file
    import json
    from src.evaluation import DEFAULT_GOLD
    listed = sum(len(c.get("known_missed", [])) for c in json.loads(DEFAULT_GOLD.read_text())["cases"])
    assert (o["recall"] == 1.0) == (listed == 0)

"""Law fetcher, SHA-256 diff detector, sync_now() and simulate_law_amendment()."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from src.schemas.regulatory import Jurisdiction, LawSyncResult, RegulatoryRule

from .linkup_scout import get_scout
from .seed_laws import SEED_RULES
from .store import get_store

_OVERLAY: dict[str, RegulatoryRule] = {}  # simulated upstream amendments
_OVERLAY_LOCK = threading.Lock()
_SIM_COUNTER = 0


def reset_overlay() -> None:
    global _SIM_COUNTER
    with _OVERLAY_LOCK:
        _OVERLAY.clear()
        _SIM_COUNTER = 0


def fetch_remote_rules() -> tuple[dict[str, RegulatoryRule], str]:
    """Return (rules, source). Order: LAW_FEED_URL (JSON) > LAW_FEED_FILE (JSON) > seed. Simulated overlay always applies."""
    rules = {r.rule_id: r for r in SEED_RULES}
    source = "seed"
    raw = None
    feed_url, feed_file = os.getenv("LAW_FEED_URL"), os.getenv("LAW_FEED_FILE")
    try:
        if feed_url:
            import httpx

            raw = httpx.get(feed_url, timeout=10).json()
            source = feed_url
        elif feed_file and Path(feed_file).is_file():
            raw = json.loads(Path(feed_file).read_text(encoding="utf-8"))
            source = feed_file
    except Exception:
        raw = None  # upstream unreachable -> keep seed baseline
    if isinstance(raw, list):
        for item in raw:
            try:
                r = RegulatoryRule.model_validate(item).sealed()
                rules[r.rule_id] = r
            except Exception:
                continue
    with _OVERLAY_LOCK:
        rules.update(_OVERLAY)
        if _OVERLAY:
            source += "+simulated"
    return rules, source


def sync_now() -> LawSyncResult:
    """Fetch upstream rules, SHA-256 diff against the live index, swap atomically and re-index."""
    rules, source = fetch_remote_rules()
    scout = get_scout()
    if scout.enabled:  # live Linkup deep search: attach verified source_url citations to every rule
        rules = scout.enrich(rules)
        source += "+linkup"
    return get_store().apply(rules, source)


def simulate_law_amendment(
    jurisdiction: Jurisdiction = "EU_AI_ACT",
    title: str | None = None,
    text: str | None = None,
) -> LawSyncResult:
    """Inject a new EU/UK regulatory rule update upstream, then sync (logs the diff, re-indexes atomically)."""
    global _SIM_COUNTER
    with _OVERLAY_LOCK:
        _SIM_COUNTER += 1
        n = _SIM_COUNTER
    defaults = {
        "EU_AI_ACT": ("EU AI Act", "Simulated amendment: providers of generative systems must additionally expose a "
                      "public detection API for machine-readable watermarks."),
        "UK_GDPR_ICO": ("UK GDPR / ICO", "Simulated update: ICO guidance requires logging of every human override of an "
                        "automated decision."),
        "UK_DSIT": ("DSIT", "Simulated update: DSIT adds a sixth principle on provenance of training data."),
        "UK_COPYRIGHT_TDM": ("UK Copyright", "Simulated update: UK TDM exception clarified to exclude commercial model training."),
    }
    label, default_text = defaults[jurisdiction]
    rule = RegulatoryRule(
        rule_id=f"{jurisdiction}:SIM.Amendment-{n}", jurisdiction=jurisdiction, reference=f"{label} simulated amendment {n}",
        title=title or f"[SIMULATED] {label} amendment {n}", text=text or default_text,
        keywords=["simulated", "amendment", jurisdiction.lower()], effective_from=None,
    ).sealed()
    with _OVERLAY_LOCK:
        _OVERLAY[rule.rule_id] = rule
    result = sync_now()
    result.log.insert(0, f"simulated upstream amendment injected: {rule.rule_id}")
    return result

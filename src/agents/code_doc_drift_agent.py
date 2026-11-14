from __future__ import annotations

from .tracing import traced
from .base import (MicroAgent, Verdict, decision_candidates, ev_card, ev_chunk, ev_dep, ev_slice, external_entries,
                   generation_entries, slice_regions)

# claim_type -> function(ix) -> (state, code_evidence, detail)
# state: CONTRADICTS | SUPPORTS | UNVERIFIABLE


def _privacy(ix):
    if not ix.has_code:
        return "UNVERIFIABLE", [], "no code available"
    ext = external_entries(ix)
    bad = [s for s in ext if not s.has_pii_redaction]
    if bad:
        return "CONTRADICTS", [ev_slice(s) for s in bad[:3]], "external calls carry personal data with no redaction step"
    return "SUPPORTS", [ev_slice(s) for s in ext[:2]], "redaction present (or no external flows)"


def _hosting(ix):
    if not ix.has_code:
        return "UNVERIFIABLE", [], "no code available"
    ext = external_entries(ix)
    us = [s for s in ext if "US" in slice_regions(s)]
    if us:
        urls = sorted({u for s in us for u, r in s.endpoint_regions.items() if r == "US"})
        return "CONTRADICTS", [ev_slice(s) for s in us[:3]], f"code calls US-region endpoint(s): {', '.join(urls)}"
    unk = [s for s in ext if "UNKNOWN" in slice_regions(s)]
    if unk:
        return "UNVERIFIABLE", [ev_slice(s) for s in unk[:3]], "endpoint region could not be determined"
    return "SUPPORTS", [ev_slice(s) for s in ext[:2]], "all endpoints EU/UK/internal"


def _hitl(ix):
    if not ix.has_code:
        return "UNVERIFIABLE", [], "no code available"
    cands, _ = decision_candidates(ix)
    if not cands:
        cands = external_entries(ix)
    if not cands:
        return "UNVERIFIABLE", [], "no decision entry point located"
    bad = [s for s in cands if not s.has_hitl_gate]
    if bad:
        ev = [ev_slice(s) for s in bad[:3]] + [ev_card(c) for c in ix.cards if "no_human_gate" in c.capability_tags][:1]
        return "CONTRADICTS", ev, "decision entry point has no human approval gate"
    return "SUPPORTS", [ev_slice(s) for s in cands[:2]], "human approval gate present"


def _safety(ix):
    if not ix.has_code:
        return "UNVERIFIABLE", [], "no code available"
    gens = generation_entries(ix)
    if not gens:
        return "UNVERIFIABLE", [], "no generation endpoint located"
    risky = [c for c in ix.cards if "unmoderated_hate_speech_risk" in c.capability_tags]
    bad = [s for s in gens if not s.has_moderation_hook]
    if risky or bad:
        return "CONTRADICTS", [ev_card(c) for c in risky[:2]] + [ev_slice(s) for s in bad[:2]], \
            "generation path has no moderation hook / prompt is unfiltered"
    return "SUPPORTS", [ev_slice(s) for s in gens[:2]], "moderation hook present"


def _watermark(ix):
    if not ix.has_code:
        return "UNVERIFIABLE", [], "no code available"
    gens = generation_entries(ix)
    if not gens:
        return "UNVERIFIABLE", [], "no generation endpoint located"
    bad = [s for s in gens if not s.has_watermark_hook]
    if bad:
        return "CONTRADICTS", [ev_slice(s) for s in bad[:3]], "generated output is not marked/watermarked"
    return "SUPPORTS", [ev_slice(s) for s in gens[:2]], "watermark/AI-generated marking present"


def _ip(ix):
    deps = ix.dependencies
    if not deps:
        return "UNVERIFIABLE", [], "no dependency or model licence facts found"
    bad = [d for d in deps if d.license_class in {"STRONG_COPYLEFT", "NON_COMMERCIAL"}]
    if bad and ix.commercial:
        return "CONTRADICTS", [ev_dep(d) for d in bad[:4]], "restrictive licences: " + ", ".join(f"{d.name} ({d.license})" for d in bad)
    return "SUPPORTS", [ev_dep(d) for d in deps[:2]], "no restrictive licences found"


ASSESSORS = {"PRIVACY": _privacy, "HOSTING": _hosting, "HITL": _hitl, "SAFETY_MODERATION": _safety,
             "WATERMARK": _watermark, "IP_LICENSE": _ip}


class CodeDocDriftAgent(MicroAgent):
    name = "code_doc_drift"

    @traced("code_doc_drift_agent.evaluate")
    def evaluate(self, check, ctx) -> Verdict:
        ix = ctx.index
        claim_type = check.check_id.split("-", 1)[1]
        if not ix.has_docs:
            return Verdict("SUSPECTED_GAP", 0.6, f"No documentation to triangulate {claim_type} promise",
                           "No documents found: documentary promises cannot be compared with code (closed-world).")
        asserts = [a for a in ix.assertions if a.claim_type == claim_type]
        if not asserts:
            return Verdict("PASS", 0.85, f"No documented {claim_type} promise to contradict",
                           f"{len(ix.chunks)} document section(s) reviewed; none makes a {claim_type} promise.", scan_basis=True)
        chunk_by_id = {c.chunk_id: c for c in ix.chunks}
        a0 = asserts[0]
        doc_ev = [ev_chunk(chunk_by_id[a.source_chunk_id], a.claim_text) for a in asserts[:2] if a.source_chunk_id in chunk_by_id]
        state, code_ev, detail = ASSESSORS[claim_type](ix)
        claim = f'Docs promise: "{a0.claim_text}"'
        if state == "CONTRADICTS":
            return Verdict("CONFIRMED_VIOLATION", 0.92, f"Code-vs-doc drift: {claim_type} promise contradicted by code",
                           f"Documentary promise is contradicted by implementation ({detail}).", doc_ev + code_ev,
                           drift=f"{claim} | Code shows: {detail}.")
        if state == "SUPPORTS":
            return Verdict("PASS", 0.88, f"{claim_type} promise consistent with code", f"Implementation matches the documented promise ({detail}).",
                           doc_ev + code_ev, drift=None)
        return Verdict("SUSPECTED_GAP", 0.6, f"{claim_type} promise could not be verified in code",
                       f"Promise exists in docs but code evidence is insufficient ({detail}).", doc_ev + code_ev,
                       drift=f"{claim} | Code evidence: {detail}.")

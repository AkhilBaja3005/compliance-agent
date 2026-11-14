"""Gate 3: deterministic entailment — does the cited evidence logically support the finding status?"""
from __future__ import annotations

import re

from src.edge_extractors.code_scanner import classify_endpoint, URL_RE
from src.schemas.findings import ComplianceFinding

from .common import GateContext, quarantine

GATE = "gate3_entailment"
DPA_RX = {
    "DPA-01": r"zero[- ]data[- ]retention|\bZDR\b|no[- ]retention|not (be )?(retain|stor)|not used (to|for) train",
    "DPA-02": r"text[- ]and[- ]data[- ]mining|\bTDM\b|opt[- ]out|copyright policy|provenance",
    "DPA-03": r"annex\s+iv|technical documentation",
    "DPA-04": r"\bDPIA\b|data protection impact assessment",
}
RESTRICT = {"STRONG_COPYLEFT", "NON_COMMERCIAL"}


def _lookup(ctx: GateContext):
    ix = ctx.index
    m = {}
    for s in ix.slices:
        m[s.slice_id] = ("slice", s)
    for c in ix.cards:
        m[c.module_id] = ("card", c)
    for d in ix.chunks:
        m[d.chunk_id] = ("chunk", d)
    for d in ix.dependencies:
        m[d.dep_id] = ("dep", d)
    return m


def _base_rules(base: str, arts: list, want: str) -> bool:
    """Does the artifact set support `want` ('V' violation / 'P' pass) for check family `base`?"""
    sl = [o for k, o in arts if k == "slice"]
    cards = [o for k, o in arts if k == "card"]
    deps = [o for k, o in arts if k == "dep"]
    chunks = [o for k, o in arts if k == "chunk"]
    if base == "PII-01":
        return any((s.calls_ai_sdk or s.calls_http or s.external_endpoints) and not s.has_pii_redaction for s in sl) if want == "V" \
            else any(s.has_pii_redaction for s in sl)
    if base == "PII-02":
        regs = [set(s.endpoint_regions.values()) for s in sl]
        return any("US" in r for r in regs) if want == "V" else any(r and r <= {"EU_UK", "INTERNAL"} for r in regs)
    if base in {"HITL-01", "HITL-02"}:
        if want == "V":
            return any(not s.has_hitl_gate for s in sl) or any("no_human_gate" in c.capability_tags for c in cards)
        return any(s.has_hitl_gate for s in sl)
    if base == "SAFE-01":
        if want == "V":
            return any("unmoderated_hate_speech_risk" in c.capability_tags for c in cards) or any(s.is_generation and not s.has_moderation_hook for s in sl)
        return any(s.is_generation and s.has_moderation_hook for s in sl)
    if base == "SAFE-02":
        return any(s.is_generation and not s.has_watermark_hook for s in sl) if want == "V" \
            else any(s.has_watermark_hook for s in sl)
    if base == "OSS-01":
        pk = [d for d in deps if d.kind == "package"]
        return any(d.license_class in RESTRICT for d in pk) if want == "V" else any(d.license_class not in RESTRICT for d in pk)
    if base == "OSS-02":
        mw = [d for d in deps if d.kind == "model_weights"]
        return any(d.license_class in RESTRICT for d in mw) if want == "V" else any(d.license_class not in RESTRICT for d in mw)
    if base in DPA_RX:
        return want == "P" and any(re.search(DPA_RX[base], c.text, re.I) for c in chunks)
    return True


def _supports(check_id: str, status: str, arts: list) -> bool:
    want = "V" if status == "CONFIRMED_VIOLATION" else "P"
    if check_id.startswith("DRIFT-"):
        code = [a for a in arts if a[0] != "chunk"]
        has_doc = any(k == "chunk" for k, _ in arts)
        if not has_doc or not code:
            return False
        claim = check_id.split("-", 1)[1]
        base = {"PRIVACY": ["PII-01"], "HOSTING": ["PII-02"], "HITL": ["HITL-01"], "SAFETY_MODERATION": ["SAFE-01"],
                "WATERMARK": ["SAFE-02"], "IP_LICENSE": ["OSS-01", "OSS-02"]}[claim]
        return any(_base_rules(b, code, want) for b in base)
    return _base_rules(check_id, arts, want)


def apply(findings: list[ComplianceFinding], ctx: GateContext) -> list[ComplianceFinding]:
    lookup = _lookup(ctx)
    texts = ctx.index.artifact_text()
    out, n = [], 0
    for f in findings:
        if f.status not in {"CONFIRMED_VIOLATION", "PASS"}:
            out.append(f)
            continue
        reasons = []
        if f.status == "CONFIRMED_VIOLATION" and not f.evidence:
            reasons.append("confirmed violation cites no evidence")
        arts = []
        for e in f.evidence:
            if e.artifact_id not in lookup:
                continue  # gate 1 already handled unknown artifacts
            arts.append(lookup[e.artifact_id])
            kind = lookup[e.artifact_id][0]
            if kind != "card":
                norm_art = " ".join(texts.get(e.artifact_id, "").split())
                snip = e.snippet.rstrip("…").strip()
                if snip and snip not in norm_art and "[REDACTED" not in snip:
                    reasons.append(f"snippet for '{e.artifact_id}' is not contained in the cited artifact")
        if f.evidence and f.check_id and not _supports(f.check_id, f.status, arts):
            reasons.append(f"cited evidence does not logically support {f.status} for {f.check_id}")
        if reasons:
            n += 1
            f = quarantine(f, "; ".join(reasons), GATE)
        out.append(f)
    ctx.trace.append(f"guardrail gate3_entailment: {n} quarantined")
    return out

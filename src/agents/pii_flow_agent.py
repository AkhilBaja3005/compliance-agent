from __future__ import annotations

from .tracing import traced
from .base import (MicroAgent, Verdict, ev_slice, external_entries, no_code_verdict, pii_likely, slice_regions)


class PIIFlowAgent(MicroAgent):
    name = "pii_flow"

    @traced("pii_flow_agent.evaluate")
    def evaluate(self, check, ctx) -> Verdict:
        ix = ctx.index
        if check.check_id.startswith("GDPR-"):
            from .gdpr_checks import evaluate_gdpr

            return evaluate_gdpr(check.check_id, ix)
        if not ix.has_code:
            return no_code_verdict(f"{check.check_id}: no code to inspect")
        ext = external_entries(ix)
        if not ext:
            return Verdict("PASS", 0.85, "No external AI/HTTP data flows detected",
                           f"Scanned {len(ix.py_files)} Python file(s); no entry point calls an external AI SDK or HTTP endpoint.",
                           scan_basis=True)
        if check.check_id == "PII-01":
            bad = [s for s in ext if not s.has_pii_redaction]
            if not bad:
                return Verdict("PASS", 0.9, "PII redaction present before external calls",
                               "Every entry point that reaches an external endpoint applies PII redaction/masking.",
                               [ev_slice(s) for s in ext[:4]])
            confirmed = [s for s in bad if pii_likely(s, ix)]
            if confirmed:
                return Verdict("CONFIRMED_VIOLATION", 0.9, "Personal data sent to external service without redaction",
                               f"{len(confirmed)} entry point(s) forward personal data to external endpoints with no redaction/masking step in the call path.",
                               [ev_slice(s) for s in confirmed[:4]])
            return Verdict("SUSPECTED_GAP", 0.6, "No PII redaction evidence on external calls",
                           "External calls show no redaction step; PII content could not be ruled out.", [ev_slice(s) for s in bad[:4]])
        # PII-02 residency
        us = [s for s in ext if "US" in slice_regions(s)]
        unk = [s for s in ext if "UNKNOWN" in slice_regions(s) and s not in us]
        if us:
            conf = [s for s in us if pii_likely(s, ix)]
            ev = [ev_slice(s) for s in (conf or us)[:4]]
            urls = sorted({u for s in us for u, r in s.endpoint_regions.items() if r == "US"})
            if conf:
                return Verdict("CONFIRMED_VIOLATION", 0.92, "Personal data processed on US-hosted endpoint",
                               f"Code sends personal data to US-region endpoint(s): {', '.join(urls)}.", ev)
            return Verdict("SUSPECTED_GAP", 0.7, "US-hosted endpoint in use", f"US-region endpoint(s) in use: {', '.join(urls)}.", ev)
        if unk:
            return Verdict("SUSPECTED_GAP", 0.6, "External endpoint region could not be determined",
                           "At least one endpoint is dynamic or has an unrecognised region; EU residency is unproven.",
                           [ev_slice(s) for s in unk[:4]])
        return Verdict("PASS", 0.9, "All external endpoints are in EU (or internal)",
                       "Every external endpoint resolves to an EU region or an internal host.", [ev_slice(s) for s in ext[:4]])

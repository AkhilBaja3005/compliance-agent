from __future__ import annotations

import re

from .tracing import traced
from .base import MicroAgent, Verdict, ev_chunk

PATTERNS = {
    "DPA-01": [r"zero[- ]data[- ]retention|\bZDR\b|no[- ]retention|not (be )?(retain|stor)|not used (to|for) train"],
    "DPA-02": [r"text[- ]and[- ]data[- ]mining|\bTDM\b|opt[- ]out|copyright policy|training[- ]data provenance|provenance"],
    "DPA-03": [r"annex\s+iv|technical documentation"],
    "DPA-04": [r"\bDPIA\b|data protection impact assessment"],
}
TITLES = {
    "DPA-01": "zero-data-retention (ZDR) / no-training clause in provider DPA",
    "DPA-02": "TDM copyright policy and training-data provenance",
    "DPA-03": "Annex IV technical documentation",
    "DPA-04": "Data Protection Impact Assessment",
}


class DPAProvenanceAgent(MicroAgent):
    name = "dpa_provenance"

    @traced("dpa_provenance_agent.evaluate")
    def evaluate(self, check, ctx) -> Verdict:
        ix = ctx.index
        if check.check_id.startswith("GDPR-"):
            from .gdpr_checks import evaluate_gdpr

            return evaluate_gdpr(check.check_id, ix)
        if check.check_id.startswith("DATA-"):
            from .data_governance import evaluate_data

            return evaluate_data(check.check_id, ix)
        label = TITLES[check.check_id]
        if not ix.chunks:
            return Verdict("SUSPECTED_GAP", 0.6, f"No documents to evidence {label}",
                           "No policy/DPA documents were found for this tenant (closed-world: no evidence ≠ pass).")
        rx = re.compile(PATTERNS[check.check_id][0], re.I)
        hits = []
        for c in ix.chunks:
            for sent in re.split(r"(?<=[.!?])\s+|\n", c.text):
                if rx.search(sent):
                    hits.append(ev_chunk(c, sent.strip()))
                    break
        if hits:
            return Verdict("PASS", 0.88, f"Documentary evidence of {label}",
                           f"Found {len(hits)} document section(s) addressing {label}.", hits[:3])
        return Verdict("SUSPECTED_GAP", 0.7, f"Missing documentary evidence of {label}",
                       f"No document section addresses {label}.")

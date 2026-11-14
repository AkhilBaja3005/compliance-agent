"""EU GDPR checks (GDPR-01..06). Conservative: a legal mechanism that cannot be seen is a SUSPECTED_GAP, not a proven violation.

Cross-border transfers to the US are lawful with an adequacy decision / SCCs / BCRs, so GDPR-01 never confirms a violation from a
US endpoint alone; it confirms nothing and asks for the documented mechanism. Automated decisions without a human gate and without a
documented right to human intervention are confirmed (Art. 22) because both code and documents were examined.
"""
from __future__ import annotations

import re

from .base import (Verdict, decision_candidates, ev_card, ev_chunk, ev_data, ev_slice, external_entries, no_code_verdict, slice_regions)

TRANSFER_RE = re.compile(r"standard contractual clauses|\bSCCs?\b|binding corporate rules|\bBCRs?\b|adequacy decision|data privacy framework|\bDPF\b|art(icle|\.)? ?46|chapter v\b|transfer impact assessment|\bTIA\b", re.I)
CONTEST_RE = re.compile(r"\bcontest\w*|human intervention|right to (a )?human|article 22|art\.? ?22|appeal\w*|request (a )?(human )?review|challenge (the )?decision", re.I)
ART28_TERMS = {
    "documented instructions": re.compile(r"documented instructions|only on (the )?(controller'?s )?instructions|act only on", re.I),
    "confidentiality": re.compile(r"confidential\w*", re.I),
    "security": re.compile(r"security measures|appropriate (technical|security)|art(icle|\.)? ?32|encrypt\w*", re.I),
    "sub-processors": re.compile(r"sub-?processors?", re.I),
    "deletion/return": re.compile(r"delet\w+|return (of )?(the )?data|erasure|end of (the )?(services?|contract)", re.I),
    "audit": re.compile(r"\baudit\w*|inspection\w*", re.I),
}
DPIA_RE = re.compile(r"\bDPIA\b|data protection impact assessment|art(icle|\.)? ?35", re.I)
ART9_RE = re.compile(r"explicit consent|art(icle|\.)? ?9\(?2?\)?|substantial public interest|vital interests|special[- ]categor\w+ (data )?(basis|condition)|health(care)? provision", re.I)
SPECIAL_CODE_RE = re.compile(r"\b(diagnos\w*|patient|medical|health|ethnic\w*|race|religio\w*|biometric|genetic|sexual orientation|trade union|political opinion)\b", re.I)


def _docs(ix, rx: re.Pattern, n: int = 3):
    out = []
    for c in ix.chunks:
        for sent in re.split(r"(?<=[.!?])\s+|\n", c.text):
            if rx.search(sent):
                out.append(ev_chunk(c, sent.strip()))
                break
        if len(out) >= n:
            break
    return out


def evaluate_gdpr(check_id: str, ix) -> Verdict:
    if check_id == "GDPR-01":
        if not ix.has_code and not ix.data_assets:
            return no_code_verdict("GDPR-01: no code to inspect")
        us = [s for s in external_entries(ix) if "US" in slice_regions(s)]
        infra = [c for c in ix.cards if "infra_region_us" in c.capability_tags]
        data_us = [a for a in ix.data_assets if a.get("region") and re.match(r"(?i)^(us|usa)[-_]|^(east|west|central)us", a["region"])]
        if not (us or infra or data_us):
            return Verdict("PASS", 0.8, "No transfers to US/non-EU recipients detected", "No external endpoint, infrastructure region or data store outside the EU was found.", scan_basis=True)
        ev = [ev_slice(s) for s in us[:2]] + [ev_card(c) for c in infra[:2]] + [ev_data(a, f"region={a['region']}") for a in data_us[:1]]
        docs = _docs(ix, TRANSFER_RE)
        if docs:
            return Verdict("PASS", 0.7, "Transfer mechanism documented", "Personal data reaches US/non-EU recipients and a Chapter V mechanism (SCCs / DPF / BCRs) is documented. The mechanism's validity is not verified.", ev + docs)
        return Verdict("SUSPECTED_GAP", 0.8, "Transfer to US/non-EU recipient without a documented Chapter V mechanism",
                       "Data flows to a recipient or region outside the EU, and no document names an adequacy decision, standard contractual clauses or binding corporate rules (GDPR Arts. 44-46).", ev)
    if check_id == "GDPR-02":
        if not ix.has_code:
            return no_code_verdict("GDPR-02: no code to inspect")
        cands, explicit = decision_candidates(ix)
        if not cands:
            return Verdict("SUSPECTED_GAP", 0.6, "Automated-decision handling could not be located", "No decision entry point was identified, so Art. 22 safeguards are unproven.")
        bad = [s for s in cands if not s.has_hitl_gate]
        docs = _docs(ix, CONTEST_RE)
        if not bad:
            return Verdict("PASS", 0.85, "Human intervention present on automated decisions", "Decision entry points route outcomes through human review.", [ev_slice(s) for s in cands[:3]])
        if docs:
            return Verdict("SUSPECTED_GAP", 0.7, "No human gate in code; a contest right is documented but not enforced in code",
                           f"{len(bad)} decision entry point(s) lack human review, while documents describe a right to contest. Whether the process works in practice is unverified.", [ev_slice(s) for s in bad[:3]] + docs)
        if explicit:
            return Verdict("CONFIRMED_VIOLATION", 0.85, "Solely automated decisions without human intervention or contest route",
                           f"{len(bad)} decision entry point(s) have no human review and no document describes a right to human intervention or to contest (Art. 22(3)).", [ev_slice(s) for s in bad[:3]])
        return Verdict("SUSPECTED_GAP", 0.65, "No Art. 22 safeguards evidenced for decisions in a high-risk sector", "Decision entry points show no human review or contest route.", [ev_slice(s) for s in bad[:3]])
    if check_id == "GDPR-03":
        ext = external_entries(ix) if ix.has_code else []
        dpa = [c for c in ix.chunks if re.search(r"\bDPA\b|data processing (agreement|addendum)|processor", c.text + " " + c.doc_name, re.I)]
        if not dpa:
            return Verdict("SUSPECTED_GAP", 0.75, "No processor agreement (DPA) evidenced for external providers",
                           ("External AI/HTTP providers receive data" if ext else "No processor agreement was found") + " and no data processing agreement document exists (Art. 28(3)).",
                           [ev_slice(s) for s in ext[:2]])
        text = " ".join(c.text for c in dpa)
        have = [k for k, rx in ART28_TERMS.items() if rx.search(text)]
        missing = [k for k in ART28_TERMS if k not in have]
        if len(have) >= 5:
            return Verdict("PASS", 0.8, "Processor agreement contains the Art. 28(3) terms", f"Terms found: {', '.join(have)}.", [ev_chunk(dpa[0])])
        return Verdict("SUSPECTED_GAP", 0.8, "Processor agreement misses Art. 28(3) terms", f"Found: {', '.join(have) or 'none'}; not found: {', '.join(missing)}.", [ev_chunk(d) for d in dpa[:2]])
    if check_id == "GDPR-04":
        docs = _docs(ix, DPIA_RE)
        if docs:
            return Verdict("PASS", 0.85, "DPIA documented", f"{len(docs)} document section(s) reference a DPIA.", docs)
        return Verdict("SUSPECTED_GAP", 0.75, "No DPIA evidenced for high-risk processing",
                       "The system processes personal data or makes automated decisions and no document references a DPIA (Art. 35).")
    if check_id == "GDPR-05":
        special_cols = [a for a in ix.data_assets if any("special_category" in c.get("classes", []) for c in a.get("columns", []))]
        code_hits = [s for s in ix.slices if SPECIAL_CODE_RE.search(s.code_snippet)]
        if not special_cols and not code_hits:
            return Verdict("PASS", 0.75, "No special-category data detected", "No special-category columns or identifiers were found in data schemas or code.", scan_basis=True)
        ev = [ev_data(a) for a in special_cols[:2]] + [ev_slice(s) for s in code_hits[:2]]
        docs = _docs(ix, ART9_RE)
        if docs:
            return Verdict("PASS", 0.7, "Art. 9(2) condition documented", "Special-category data is processed and a condition (e.g. explicit consent) is documented. Its validity is not verified.", ev + docs)
        return Verdict("SUSPECTED_GAP", 0.8, "Special-category data without a documented Art. 9(2) condition",
                       "Special-category data (health, biometric, ethnicity, beliefs, genetic) is handled and no document states an Art. 9(2) condition such as explicit consent.", ev)
    # GDPR-06 security of processing
    secrets = [c for c in ix.cards if "infra_hardcoded_secret" in c.capability_tags]
    plain = [s for s in (external_entries(ix) if ix.has_code else []) if any(u.startswith("http://") and "localhost" not in u for u in s.external_endpoints)]
    if secrets or plain:
        why = []
        if secrets:
            why.append(f"{len(secrets)} hard-coded credential-like value(s) (values withheld)")
        if plain:
            why.append(f"{len(plain)} entry point(s) send data over plaintext http://")
        return Verdict("SUSPECTED_GAP", 0.8, "Weak security measures for personal data", "; ".join(why) + ". Appropriate technical measures are required (Art. 32).",
                       [ev_card(c) for c in secrets[:3]] + [ev_slice(s) for s in plain[:2]])
    return Verdict("PASS", 0.75, "No hard-coded credentials or plaintext transport found", "Configuration and code show no hard-coded credential-like values or plaintext external transport.", scan_basis=True)

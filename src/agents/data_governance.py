"""DATA-01..05: governance checks over scanned data assets (schemas/manifests/cards) and policy documents.

Evidence is column names, classifications and provenance keys only. Closed-world: a dataset with personal/special-category columns and
no documentary safeguard is a SUSPECTED_GAP, never a PASS.
"""
from __future__ import annotations

import re

from .base import Verdict, ev_chunk, ev_data

BIAS_RE = re.compile(r"\b(bias|representativ\w*|data governance|fairness|examin\w+ (of )?(the )?data|data quality)\b", re.I)
SPECIAL_SAFEGUARD_RE = re.compile(r"\b(special[- ]categor\w*|article 9|art\.? ?9|explicit consent|pseudonymi[sz]\w*|encrypt\w*|access control|need[- ]to[- ]know)\b", re.I)
RETENTION_RE = re.compile(r"\b(retention|retain(ed)? for|delete[ds]? after|deletion|erasure|purge[ds]?|storage limitation)\b", re.I)
LAWFUL_RE = re.compile(r"\b(lawful basis|explicit consent|consent|enrol(l)?ed|opt[- ]in|subject submission)\b", re.I)
BAD_LICENSE_RE = re.compile(r"(?i)\bNC\b|-NC|non[- ]?commercial|research[- ]only")


def _doc_hits(ix, rx: re.Pattern, n: int = 2):
    out = []
    for c in ix.chunks:
        for sent in re.split(r"(?<=[.!?])\s+|\n", c.text):
            if rx.search(sent):
                out.append(ev_chunk(c, sent.strip()))
                break
        if len(out) >= n:
            break
    return out


def _cols(a, cls):
    return [c for c in a.get("columns", []) if cls in c.get("classes", [])]


def evaluate_data(check_id: str, ix) -> Verdict:
    assets = ix.data_assets
    personal = [a for a in assets if _cols(a, "pii") or _cols(a, "special_category") or _cols(a, "protected_attribute")]
    special = [a for a in assets if _cols(a, "special_category")]
    if check_id == "DATA-01":
        if not personal:
            return Verdict("PASS", 0.8, "No personal or protected-attribute data columns found", f"{len(assets)} data asset(s) scanned; none hold personal or protected-attribute columns.", scan_basis=True)
        docs = _doc_hits(ix, BIAS_RE)
        ev = [ev_data(a) for a in personal[:2]]
        if docs:
            return Verdict("PASS", 0.8, "Data governance / bias examination is documented", f"{len(personal)} dataset(s) hold personal or protected-attribute data; documentation addresses governance or bias examination.", ev + docs)
        return Verdict("SUSPECTED_GAP", 0.75, "No data-governance or bias-examination evidence for datasets with personal data",
                       f"{len(personal)} dataset(s) hold personal or protected-attribute columns, but no document addresses data governance, representativeness or bias examination (Art. 10).", ev)
    if check_id == "DATA-02":
        if not special:
            return Verdict("PASS", 0.8, "No special-category columns found", f"{len(assets)} data asset(s) scanned; no special-category columns detected.", scan_basis=True)
        docs = _doc_hits(ix, SPECIAL_SAFEGUARD_RE)
        ev = [ev_data(a) for a in special[:3]]
        if docs:
            return Verdict("PASS", 0.75, "Safeguards for special-category data are documented", "Special-category columns exist and documents describe safeguards.", ev + docs)
        return Verdict("SUSPECTED_GAP", 0.8, "Special-category data without documented safeguards",
                       f"{len(special)} dataset(s) hold special-category columns (health, biometric, ethnicity, beliefs, genetic) and no document describes an explicit basis, pseudonymisation or access control.", ev)
    if check_id == "DATA-03":
        cand = [a for a in assets if a["kind"] in {"data_card", "dvc", "csv", "parquet", "jsonl", "dbt", "uc_table", "sql_table"}]
        bad = [a for a in assets if a.get("license") and BAD_LICENSE_RE.search(a["license"])]
        if bad and ix.has_code is not None:
            return Verdict("CONFIRMED_VIOLATION", 0.85, "Dataset licence forbids commercial use", f"Dataset licence {bad[0]['license']!r} is non-commercial / research-only; commercial training or use is not permitted.",
                           [ev_data(a, f"licence={a['license']}") for a in bad[:3]], risk_tier="NON_COMPLIANT_IP")
        cards = [a for a in assets if a["kind"] in {"data_card", "dvc"}]
        if not cards:
            if not cand:
                return Verdict("PASS", 0.7, "No datasets to evidence", "No datasets were found.", scan_basis=True)
            return Verdict("SUSPECTED_GAP", 0.75, "No data card / manifest declaring source, licence and lineage",
                           f"{len(cand)} dataset(s) found without a data card or manifest declaring source, licence, lineage and TDM opt-out handling.", [ev_data(a) for a in cand[:3]])
        missing = [a for a in cards if not (a.get("license") and a["meta"].get("source") and a["meta"].get("lineage"))]
        if missing:
            return Verdict("SUSPECTED_GAP", 0.75, "Data card missing source, licence or lineage",
                           f"{len(missing)} data card(s) lack one of: licence, source, lineage.", [ev_data(a) for a in missing[:3]])
        return Verdict("PASS", 0.8, "Datasets declare source, licence and lineage", f"{len(cards)} data card(s) declare source, licence and lineage.", [ev_data(a) for a in cards[:3]])
    if check_id == "DATA-04":
        if not personal:
            return Verdict("PASS", 0.8, "No personal data columns found", "No datasets hold personal data; no retention rule needed.", scan_basis=True)
        cards = [a for a in personal if a["meta"].get("retention")]
        docs = _doc_hits(ix, RETENTION_RE)
        if docs or cards:
            return Verdict("PASS", 0.75, "Retention/deletion is documented", "Documents or data cards state retention or deletion rules.", [ev_data(a) for a in (cards or personal)[:2]] + docs)
        return Verdict("SUSPECTED_GAP", 0.75, "No retention or deletion rule for personal data", f"{len(personal)} dataset(s) hold personal data and no document or data card states retention or deletion.", [ev_data(a) for a in personal[:3]])
    # DATA-05 biometric
    bio = [a for a in assets if any("biometric" in c.get("tags", []) for c in a.get("columns", []))]
    scraped = [a for a in assets if a["meta"].get("scraped") == "true"]
    if bio and scraped:
        return Verdict("CONFIRMED_VIOLATION", 0.9, "Biometric data acquired by untargeted scraping",
                       "A dataset holding facial/biometric data is described as scraped / crawled / untargeted; creating or expanding facial-recognition databases that way is prohibited (Art. 5(1)(e)).",
                       [ev_data(a) for a in (bio + scraped)[:3]], risk_tier="PROHIBITED")
    if bio:
        docs = _doc_hits(ix, LAWFUL_RE)
        if docs:
            return Verdict("PASS", 0.7, "Lawful basis documented for biometric data", "Biometric columns exist and documents state consent / enrolment.", [ev_data(a) for a in bio[:2]] + docs)
        return Verdict("SUSPECTED_GAP", 0.8, "Biometric data without documented lawful basis", f"{len(bio)} dataset(s) hold biometric columns and no document states consent, enrolment or another lawful basis.", [ev_data(a) for a in bio[:3]])
    return Verdict("PASS", 0.8, "No biometric data columns found", f"{len(assets)} data asset(s) scanned; no biometric columns.", scan_basis=True)

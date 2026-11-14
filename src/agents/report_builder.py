"""Report-level assembly: compliance matrix, eval results, fairness metrics, roadmap, coverage, readiness, bundle hash."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime

from src.edge_extractors.code_scanner import PII_INDICATOR_RE  # noqa: F401 (re-exported for convenience)
from src.schemas.findings import ComplianceFinding, TriagedAuditReport

STATUS_RANK = {"CONFIRMED_VIOLATION": 0, "QUARANTINED_FOR_HUMAN_REVIEW": 1, "SUSPECTED_GAP": 2, "PASS": 3, "NOT_ASSESSED": 4}
SEV_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4, None: 5}
PROTECTED_RE = re.compile(r"\b(gender|sex|race|ethnic\w*|age|religio\w*|disabilit\w*|nationality|postcode|marital)\b", re.I)
FAIRNESS_DOC_RE = re.compile(r"\b(bias|fairness|disparate impact|demographic parity|equali[sz]ed odds|protected characteristic\w*)\b", re.I)
DPA_DOC_RE = re.compile(r"\b(DPA|DPIA|data processing agreement|zero data retention|ZDR|annex iv|data protection impact)\b", re.I)


def bundle_hash(findings: list[ComplianceFinding]) -> str:
    rows = sorted((f.finding_id, f.status, sorted(e.sha256_hash for e in f.evidence)) for f in findings)
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def build_compliance_matrix(findings: list[ComplianceFinding], law_store) -> list[dict]:
    by_rule: dict[str, list[ComplianceFinding]] = {}
    for f in findings:
        by_rule.setdefault(f.primary_rule or f.regulatory_reference, []).append(f)
    rows = []
    for rid, rule in sorted(law_store.snapshot().items()):
        fs = by_rule.get(rid, [])
        status = min((f.status for f in fs), key=lambda s: STATUS_RANK[s]) if fs else "NOT_ASSESSED"
        sev = min((f.severity for f in fs if f.severity), key=lambda s: SEV_RANK[s], default=None)
        rows.append({"rule_id": rid, "reference": rule.reference, "jurisdiction": rule.jurisdiction, "status": status,
                     "max_severity": sev, "check_ids": sorted({f.check_id for f in fs if f.check_id}),
                     "finding_ids": [f.finding_id for f in fs], "linkup_source_url": rule.linkup_source_url})
    return rows


def build_fairness(ix, profile) -> dict:
    prot = sorted({m.group(0).lower() for s in ix.slices for m in PROTECTED_RE.finditer(s.code_snippet)})
    docs = [c for c in ix.chunks if FAIRNESS_DOC_RE.search(c.text)]
    needs = profile.automated_decisions or profile.high_risk_sector
    if not needs and not prot:
        status = "NOT_APPLICABLE"
    else:
        status = "DOCUMENTED" if docs else "SUSPECTED_GAP"  # closed-world: no evidence of bias testing -> gap
    return {"status": status, "protected_attributes_in_code": prot, "bias_testing_documented": bool(docs),
            "evidence_chunk_ids": [c.chunk_id for c in docs[:3]], "automated_decisions": profile.automated_decisions,
            "note": "Deterministic screen only; no statistical fairness metrics were computed (no model outputs supplied)."}


def build_roadmap(findings: list[ComplianceFinding]) -> list[dict]:
    open_f = [f for f in findings if f.status != "PASS"]
    open_f.sort(key=lambda f: (SEV_RANK[f.severity], f.due_date or datetime.max.date(), f.finding_id))
    roadmap = []
    for i, f in enumerate(open_f, 1):
        d = f.days_remaining
        phase = "Immediate" if f.severity == "Critical" or (d is not None and d <= 30) else "Next quarter" if (d or 99) <= 90 else "Backlog"
        roadmap.append({"priority": i, "phase": phase, "finding_id": f.finding_id, "title": f.title, "severity": f.severity,
                        "owner": f.owner, "due_date": f.due_date.isoformat() if f.due_date else None, "effort_days": f.effort_days,
                        "action": (f.remediation_steps or ["Review evidence"])[0], "status": f.status,
                        "human_review_required": f.human_review_required})
    return roadmap


def build_input_coverage(ix) -> tuple[dict, float]:
    deps = [d for d in ix.dependencies if d.kind == "package"]
    kinds = {
        "code": bool(ix.py_files),
        "policy_documents": bool(ix.chunks),
        "dependency_manifest": bool(deps),
        "dpa_dpia_documents": any(DPA_DOC_RE.search(c.text) or DPA_DOC_RE.search(c.doc_name) for c in ix.chunks),
    }
    cov = {
        "kinds_present": kinds,
        "code": {"python_files": len(ix.py_files), "ast_slices": len(ix.slices), "capability_cards": len(ix.cards),
                 "commit_sha": ix.commit_sha, "origin": ix.code_origin},
        "documents": {"sections": len(ix.chunks), "documents": len({c.doc_name for c in ix.chunks}),
                      "assertions": len(ix.assertions), "confluence_pages": ix.doc_pages, "origin": ix.docs_origin},
        "dependencies": {"packages": len(deps), "model_licences": sum(d.kind == "model_weights" for d in ix.dependencies)},
        "systems": {"inventory": len(ix.systems), "declared_in_docs": sum(s.declared_in_docs for s in ix.systems),
                    "detected_in_code": sum(s.detected_in_code for s in ix.systems)},
    }
    return cov, round(100.0 * sum(kinds.values()) / len(kinds), 1)


def readiness(findings: list[ComplianceFinding]) -> tuple[str, str]:
    conf = [f for f in findings if f.status == "CONFIRMED_VIOLATION"]
    quar = [f for f in findings if f.status == "QUARANTINED_FOR_HUMAN_REVIEW"]
    gaps = [f for f in findings if f.status == "SUSPECTED_GAP"]
    crit = [f for f in conf if f.severity == "Critical"]
    if crit:
        label = "CRITICAL"
    elif conf:
        label = "NOT_READY"
    elif quar or gaps:
        label = "PARTIALLY_READY"
    else:
        label = "READY"
    summary = (f"{len(conf)} confirmed finding(s) ({len(crit)} critical), {len(gaps)} suspected gap(s), "
               f"{len(quar)} quarantined for human review, {sum(f.status == 'PASS' for f in findings)} check(s) with positive evidence. "
               "Technical audit observations only - not legal advice.")
    return label, summary


def build_eval_results(findings: list[ComplianceFinding], trace: list[str], resolved_ids: list[str], checklist_n: int) -> dict:
    by = lambda st: [f.finding_id for f in findings if f.status == st]
    hist = {h: sum(f.history_status == h for f in findings) for h in ("NEW", "RECURRING", "RESOLVED")}
    return {
        "checks_total": checklist_n, "checks_resolved": len(findings),
        "resolution_pct": round(100.0 * len(findings) / checklist_n, 1) if checklist_n else 100.0,
        "confirmed": len(by("CONFIRMED_VIOLATION")), "suspected_gaps": len(by("SUSPECTED_GAP")),
        "quarantined": by("QUARANTINED_FOR_HUMAN_REVIEW"), "passed": len(by("PASS")),
        "closed_world_gaps": len(by("SUSPECTED_GAP")),
        "human_review_required": sum(f.human_review_required for f in findings),
        "mean_confidence": round(sum(f.confidence_score for f in findings) / len(findings), 3) if findings else 0.0,
        "guardrails": [t for t in trace if t.startswith("guardrail ")],
        "history": hist, "resolved_since_last_run": resolved_ids,
    }

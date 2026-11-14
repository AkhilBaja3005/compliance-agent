"""Full audit pipeline: sources -> tri-modal index -> supervisor/agents -> guardrails -> enriched TriagedAuditReport."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.edge_extractors import TriModalIndex, build_index
from src.law_sync import get_store
from src.law_sync.linkup_scout import get_scout
from src.regulatory_rag import MandatoryCheck, build_checklist, build_profile, get_retriever
from src.schemas.findings import ComplianceFinding, TriagedAuditReport
from src.storage import DatabricksGovernanceSink, get_compliance_store

from . import report_builder as rb
from .base import AuditContext
from .enrichment import enrich_findings
from .llm_client import LLMClient
from .oss_license_agent import LinkupLicenseVerifier
from .supervisor import SupervisorAgent


@dataclass
class AgentRun:
    index: TriModalIndex
    findings: list[ComplianceFinding]
    trace: list[str]
    checklist: list[MandatoryCheck] = field(default_factory=list)
    profile: object | None = None
    checkpoint_id: str | None = None
    checkpointer_kind: str = "none"
    mlflow_trace_id: str | None = None
    assessed_at: datetime | None = None
    llm: LLMClient | None = None
    linkup_calls: int = 0


def run_agents(company_dir: Path | str | None = None, tenant_id: str | None = None, llm: LLMClient | None = None, *,
               github_source=None, confluence_source=None, space_key: str | None = None, linkup=None,
               compliance_store=None, doc_sources=None) -> AgentRun:
    store = compliance_store or get_compliance_store()
    index = build_index(company_dir, tenant_id, github_source=github_source, confluence_source=confluence_source, space_key=space_key,
                        doc_sources=doc_sources)
    law_store = get_store()
    try:  # LLM claim extraction adds paraphrased promises on top of the regex floor; offline it is a no-op
        from src.edge_extractors.doc_parser import extract_assertions_llm

        _llm = llm or LLMClient()
        known = {a.assertion_id for a in index.assertions}
        index.assertions += [a for a in extract_assertions_llm(index.chunks, _llm) if a.assertion_id not in known]
        llm = _llm
    except Exception:
        pass
    try:  # Mongo Atlas / in-memory vector indexes for rules and this tenant's artifacts
        store.index_rules(law_store.snapshot())
        store.index_tenant_artifacts(index)
    except Exception:
        pass
    profile = build_profile(index)
    applicable, not_applicable = build_checklist(profile)
    llm = llm or LLMClient()
    linkup = linkup if linkup is not None else LinkupLicenseVerifier()
    ctx = AuditContext(index=index, profile=profile, llm=llm, retriever=get_retriever(), law_store=law_store,
                       linkup=linkup, compliance_store=store)
    saver, kind = store.checkpointer()
    sup = SupervisorAgent(ctx, applicable, checkpointer=saver)
    assessed_at = datetime.now(timezone.utc)
    findings, trace = sup.run()
    findings = enrich_findings(findings, applicable, index, law_store, assessed_at)
    pre = [f"supervisor: profile sector={profile.sector} capabilities={sorted(profile.capabilities)}; "
           f"{len(applicable)} mandatory checks, {len(not_applicable)} not applicable"]
    pre += [f"supervisor: {c.check_id} not applicable for this profile (Tier A)" for c in not_applicable]
    return AgentRun(index=index, findings=findings, trace=pre + trace, checklist=applicable, profile=profile,
                    checkpoint_id=sup.checkpoint_id, checkpointer_kind=kind, mlflow_trace_id=sup.trace_id,
                    assessed_at=assessed_at, llm=llm, linkup_calls=getattr(linkup, "calls", 0))


def finalize_report(report: TriagedAuditReport, run: AgentRun, store, sink: DatabricksGovernanceSink | None = None) -> TriagedAuditReport:
    """History tagging, report-level sections, telemetry and Unity Catalog persistence."""
    law_store, ix = get_store(), run.index
    buckets = {n: getattr(report, n) for n in ("confirmed_findings", "suspected_gaps", "quarantined_for_human_review", "passed_checks")}
    flat = [f for b in buckets.values() for f in b]
    tagged, resolved_ids = store.apply_history(report.company_name, flat)
    tmap = {f.finding_id: f for f in tagged}
    for name, items in buckets.items():
        setattr(report, name, [tmap[f.finding_id] for f in items])
    findings = report.all_findings()

    report.report_id = f"AEGIS-{uuid.uuid4().hex[:12].upper()}"
    report.assessed_at = run.assessed_at
    from src.regulatory_rag.tier_a_rules import active_frameworks
    _fw = active_frameworks()
    names = {"EU_AI_ACT": "EU AI Act", "EU_GDPR": "EU GDPR", "UK_GDPR_ICO": "UK GDPR/ICO", "UK_DSIT": "UK DSIT", "UK_COPYRIGHT_TDM": "UK copyright/TDM"}
    fw_label = "EU/UK" if _fw is None else " + ".join(names.get(x, x) for x in sorted(_fw, key=lambda k: (k != "EU_AI_ACT", k)))
    report.frameworks = ["ALL"] if _fw is None else sorted(_fw)
    report.scope = (f"{len(ix.systems)} AI system(s); code: {ix.code_origin}"
                    f"{' @' + ix.commit_sha[:10] if ix.commit_sha else ''}; docs: {ix.docs_origin}; "
                    f"{len(run.checklist)} mandatory {fw_label} checks")
    report.rule_library_version = report.law_index_version
    cov, pct = rb.build_input_coverage(ix)
    report.input_coverage, report.input_coverage_pct = cov, pct
    report.overall_readiness, report.readiness_summary = rb.readiness(findings)
    report.system_inventory = ix.systems
    report.compliance_matrix = rb.build_compliance_matrix(findings, law_store)
    report.eval_results = rb.build_eval_results(findings, report.agent_execution_trace, resolved_ids, len(run.checklist))
    report.fairness_metrics = rb.build_fairness(ix, run.profile)
    report.roadmap = rb.build_roadmap(findings)
    report.bundle_sha256 = rb.bundle_hash(findings)

    linkup_urls = {u for f in findings for u in f.linkup_citation_urls} | {e.source_url for f in findings for e in f.evidence if e.source_url}
    rules_verified = sum(1 for r in law_store.snapshot().values() if r.linkup_source_url)
    sink = sink or DatabricksGovernanceSink()
    llm = run.llm
    report.stack_telemetry = {
        "databricks_endpoint": llm.databricks_endpoint if llm else None,
        "unity_catalog_table": None,
        "mlflow_trace_id": run.mlflow_trace_id,
        "mongodb_database": store.db_name if store.is_atlas else None,
        "mongodb_checkpoint_id": (run.checkpoint_id if run.checkpointer_kind == "mongodb" else
                                  f"local-memory:{run.checkpoint_id}" if run.checkpoint_id else None),
        "linkup_sources_verified_count": len(linkup_urls) if linkup_urls else rules_verified,
        "engines": {"databricks_model_serving": "live" if llm and llm.databricks_endpoint else "offline-fallback",
                    "mlflow_tracing": "live" if run.mlflow_trace_id else "no-op",
                    "unity_catalog": "live" if sink.enabled else "disabled",
                    "mongodb": "atlas" if store.is_atlas else "in-memory-fallback",
                    "linkup": "live" if (get_scout().enabled or run.linkup_calls) else "disabled"},
    }
    table = sink.persist(report)
    report.stack_telemetry["unity_catalog_table"] = table
    if sink.enabled:
        report.stack_telemetry["engines"]["unity_catalog"] = "live" if table else f"error: {sink.last_error}"
        if table:  # re-persisting would duplicate rows; telemetry is recorded in the in-memory report only
            pass
    return report


def run_audit(company_dir: Path | str | None = None, tenant_id: str | None = None, llm: LLMClient | None = None,
              tamper=None, known_tenants: set[str] | None = None, *, github_source=None, confluence_source=None,
              space_key: str | None = None, linkup=None, compliance_store=None, sink: DatabricksGovernanceSink | None = None
              ) -> TriagedAuditReport:
    """Tri-modal index -> supervisor/micro-agents -> 4-gate guardrails -> history/telemetry/Unity Catalog.

    `tamper(findings)` (optional) mutates raw findings before guardrails, e.g. to inject a fake citation hash.
    """
    from src.guardrails import apply_guardrails

    store = compliance_store or get_compliance_store()
    run = run_agents(company_dir, tenant_id, llm, github_source=github_source, confluence_source=confluence_source,
                     space_key=space_key, linkup=linkup, compliance_store=store)
    if tamper is not None:
        tamper(run.findings)
    report = apply_guardrails(run.findings, run.index, run.trace, known_tenants)
    return finalize_report(report, run, store, sink)

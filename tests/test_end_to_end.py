"""End-to-end + unit tests for the compliance auditor backend (offline, deterministic)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.agents import run_agents, run_audit
from src.agents.llm_client import LLMClient, Narrative
from src.edge_extractors import build_index
from src.edge_extractors.code_scanner import classify_endpoint
from src.guardrails import apply_guardrails
from src.guardrails.gate2_dlp_tenant import redact
from src.law_sync import get_store, simulate_law_amendment, sync_now
from src.regulatory_rag import build_checklist, build_profile, get_retriever
from src.schemas import ComplianceFinding, EvidencePointer


def audit(fixtures_dir, name):
    return run_audit(fixtures_dir / name, name)


def ids(findings):
    return {f.check_id for f in findings}


# ------------------------------------------------------------------ required end-to-end scenarios
def test_company_a_catches_pii_hosting_drift_and_missing_hitl(fixtures_dir):
    r = audit(fixtures_dir, "company_a_finscore")
    confirmed = ids(r.confirmed_findings)
    assert {"DRIFT-PRIVACY", "DRIFT-HOSTING", "DRIFT-HITL"} <= confirmed  # code-vs-doc drift
    assert {"PII-01", "PII-02", "HITL-01"} <= confirmed  # raw PII to US host, no HITL gate
    drift = next(f for f in r.confirmed_findings if f.check_id == "DRIFT-HOSTING")
    assert "us-east-1" in drift.code_vs_doc_drift and "Docs promise" in drift.code_vs_doc_drift
    assert {e.source_type for e in drift.evidence} == {"doc", "code"}


def test_company_b_catches_hate_speech_watermark_and_licences(fixtures_dir):
    r = audit(fixtures_dir, "company_b_voxgen")
    confirmed = {f.check_id: f for f in r.confirmed_findings}
    assert confirmed["SAFE-01"].risk_tier == "PROHIBITED"
    assert "SAFE-02" in confirmed and "DRIFT-WATERMARK" in confirmed
    assert "OSS-01" in confirmed and "GPL-3.0" in confirmed["OSS-01"].summary
    assert "OSS-02" in confirmed and "CC-BY-NC" in confirmed["OSS-02"].summary
    assert confirmed["SAFE-01"].human_review_required  # PROHIBITED tier is escalated, not hidden
    index = build_index(fixtures_dir / "company_b_voxgen")
    assert any("unmoderated_hate_speech_risk" in c.capability_tags for c in index.cards)


def test_company_c_has_zero_confirmed_violations(fixtures_dir):
    r = audit(fixtures_dir, "company_c_medassist")
    assert r.confirmed_findings == []
    assert r.quarantined_for_human_review == []
    assert len(r.passed_checks) >= 10


def test_fake_citation_hash_is_quarantined_not_dropped(fixtures_dir):
    run = run_agents(fixtures_dir / "company_a_finscore", "company_a_finscore")
    victim = next(f for f in run.findings if f.status == "CONFIRMED_VIOLATION" and f.evidence)
    victim.evidence[0] = victim.evidence[0].model_copy(update={"sha256_hash": "f" * 64})
    n = len(run.findings)
    report = apply_guardrails(run.findings, run.index, run.trace)
    q = {f.finding_id: f for f in report.quarantined_for_human_review}
    assert victim.finding_id in q
    assert "gate1_citations" in q[victim.finding_id].quarantine_reason
    assert q[victim.finding_id].original_status == "CONFIRMED_VIOLATION"
    total = sum(len(x) for x in (report.confirmed_findings, report.suspected_gaps,
                                 report.quarantined_for_human_review, report.passed_checks))
    assert total == n  # Quarantine-Over-Drop: nothing lost


# ------------------------------------------------------------------ extractors
def test_code_scanner_regions_and_flags(fixtures_dir):
    a = build_index(fixtures_dir / "company_a_finscore")
    s = next(x for x in a.slices if x.function_name == "score_applicant")
    assert s.endpoint_regions and set(s.endpoint_regions.values()) == {"US"}
    assert not s.has_pii_redaction and not s.has_hitl_gate and s.is_decision
    c = build_index(fixtures_dir / "company_c_medassist")
    t = next(x for x in c.slices if x.function_name == "triage_patient")
    assert t.has_pii_redaction and t.has_hitl_gate and t.has_moderation_hook and t.has_watermark_hook
    assert set(t.endpoint_regions.values()) == {"EU_UK"}
    b = build_index(fixtures_dir / "company_b_voxgen")
    assert {d.license for d in b.dependencies if d.license_class in {"STRONG_COPYLEFT", "NON_COMPLIANT", "NON_COMMERCIAL"}} \
        == {"GPL-3.0", "CC-BY-NC-4.0"}


@pytest.mark.parametrize("url,region", [
    ("https://api.openai.com/v1", "US"), ("https://api.eu.openai.com/v1", "EU_UK"),
    ("https://x.uksouth.example.net", "EU_UK"), ("http://localhost:8000", "INTERNAL"),
    ("https://llm.eu-west-1.example.eu", "EU_UK"), ("https://api.us-east-1.creditml.io", "US"),
    ("https://mystery.example.net", "UNKNOWN")])
def test_classify_endpoint(url, region):
    assert classify_endpoint(url) == region


def test_doc_parser_chunks_and_assertions(fixtures_dir):
    a = build_index(fixtures_dir / "company_a_finscore")
    chunk = next(c for c in a.chunks if c.section_header == "Hosting")
    assert chunk.line_range[0] < chunk.line_range[1] and len(chunk.sha256_hash) == 64
    assert {x.claim_type for x in a.assertions} == {"PRIVACY", "HOSTING", "HITL"}
    assert all(x.source_chunk_id in {c.chunk_id for c in a.chunks} for x in a.assertions)


def test_doc_parser_plain_text_and_pdf(tmp_path):
    from src.edge_extractors.doc_parser import parse_document

    t = tmp_path / "policy.txt"
    t.write_text("INTRO\nWe host everything in the EU.\n\nSECURITY\nPII is masked before processing.\n")
    chunks = parse_document(t, "policy.txt", "tenant")
    assert [c.section_header for c in chunks] == ["INTRO", "SECURITY"]
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(72, 72)
    with open(tmp_path / "blank.pdf", "wb") as fh:
        w.write(fh)
    blank = parse_document(tmp_path / "blank.pdf", "blank.pdf", "tenant")  # image-only PDF: visible OCR marker, never silently dropped
    heads = [c.section_header for c in blank]  # without OCR: OCR_REQUIRED; with OCR installed: an empty page is flagged LOW_OCR_CONFIDENCE
    assert "OCR_REQUIRED" in heads or "LOW_OCR_CONFIDENCE" in heads


# ------------------------------------------------------------------ closed world
def test_closed_world_empty_company_yields_gaps_never_pass(tmp_path):
    (tmp_path / "company_x_empty").mkdir()
    r = run_audit(tmp_path / "company_x_empty", "company_x_empty")
    assert r.confirmed_findings == []
    assert len(r.suspected_gaps) >= 10
    assert not any(f.status == "PASS" and not f.evidence and "PII" in (f.check_id or "") for f in r.passed_checks)


def test_supervisor_resolves_every_applicable_check(fixtures_dir):
    run = run_agents(fixtures_dir / "company_a_finscore", "company_a_finscore")
    assert {f.check_id for f in run.findings} == {c.check_id for c in run.checklist}
    assert any("supervisor: dispatch" in t for t in run.trace) and any("finish" in t for t in run.trace)
    assert any(t.startswith("pii_flow_agent") for t in run.trace)


def test_agent_failure_becomes_suspected_gap(fixtures_dir, monkeypatch):
    from src.agents import supervisor

    def boom(self, check, ctx):
        raise RuntimeError("agent crashed")

    monkeypatch.setattr(supervisor.AGENTS["oss_license"].__class__, "evaluate", boom)
    run = run_agents(fixtures_dir / "company_c_medassist", "company_c_medassist")
    oss = [f for f in run.findings if f.check_id.startswith("OSS")]
    assert oss and all(f.status == "SUSPECTED_GAP" for f in oss)


# ------------------------------------------------------------------ guardrails
def _finding(**kw):
    base = dict(finding_id="t-1", tenant_id="company_a_finscore", jurisdiction="EU_AI_ACT", regulatory_reference="EU_AI_ACT:Art.14",
                risk_tier="LIMITED_RISK", status="SUSPECTED_GAP", confidence_score=0.9, title="t", summary="s")
    base.update(kw)
    return ComplianceFinding(**base)


def test_gate1_unknown_reference_is_quarantined(fixtures_dir):
    ix = build_index(fixtures_dir / "company_a_finscore")
    r = apply_guardrails([_finding(regulatory_reference="EU_AI_ACT:Art.999")], ix)
    assert len(r.quarantined_for_human_review) == 1


def test_gate1_cross_tenant_evidence_is_quarantined(fixtures_dir):
    ix_a = build_index(fixtures_dir / "company_a_finscore")
    ix_c = build_index(fixtures_dir / "company_c_medassist")
    s = ix_c.slices[0]
    ev = EvidencePointer(source_type="code", artifact_id=s.slice_id, exact_locator=s.locator, sha256_hash=s.sha256_hash)
    r = apply_guardrails([_finding(status="CONFIRMED_VIOLATION", evidence=[ev])], ix_a)
    assert len(r.quarantined_for_human_review) == 1


def test_gate2_redacts_secrets_pii_and_tenant_leaks():
    text = "key sk-abcdefghijklmnop1234 mail jo.bloggs@example.com NI AB123456C api_key = 'hunter2hunter2' see company_b_voxgen"
    clean, changed, leaked = redact(text, "company_a_finscore", set())
    assert changed and leaked
    for needle in ("sk-abcdefghijklmnop1234", "jo.bloggs@example.com", "AB123456C", "hunter2hunter2", "company_b_voxgen"):
        assert needle not in clean


def test_gate2_applies_in_pipeline(fixtures_dir):
    ix = build_index(fixtures_dir / "company_a_finscore")
    f = _finding(summary="contact admin@corp.com about company_b_voxgen")
    r = apply_guardrails([f], ix, known_tenants={"company_b_voxgen"})
    out = (r.quarantined_for_human_review + r.suspected_gaps)[0]
    assert "admin@corp.com" not in out.summary and "company_b_voxgen" not in out.summary
    assert out.status == "QUARANTINED_FOR_HUMAN_REVIEW"  # leak -> quarantine, still reported


def test_gate3_unsupported_evidence_is_quarantined(fixtures_dir):
    ix = build_index(fixtures_dir / "company_c_medassist")
    s = next(x for x in ix.slices if x.function_name == "triage_patient")  # has redaction -> cannot support a PII violation
    ev = EvidencePointer(source_type="code", artifact_id=s.slice_id, exact_locator=s.locator,
                         sha256_hash=s.sha256_hash, snippet=s.code_snippet[:50])
    f = _finding(finding_id="t-3", tenant_id="company_c_medassist", status="CONFIRMED_VIOLATION", check_id="PII-01",
                 regulatory_reference="EU_AI_ACT:Art.10", evidence=[ev])
    r = apply_guardrails([f], ix)
    q = r.quarantined_for_human_review
    assert len(q) == 1 and "gate3_entailment" in q[0].quarantine_reason


def test_gate4_framing_and_escalation(fixtures_dir):
    ix = build_index(fixtures_dir / "company_a_finscore")
    f = _finding(risk_tier="HIGH_RISK", summary="This violates the Act and is illegal.", confidence_score=0.95)
    g = _finding(finding_id="t-2", risk_tier="LIMITED_RISK", confidence_score=0.5)
    r = apply_guardrails([f, g], ix)
    by = {x.finding_id: x for x in r.suspected_gaps}
    assert "violates" not in by["t-1"].summary and "illegal" not in by["t-1"].summary
    assert by["t-1"].human_review_required and by["t-2"].human_review_required  # high-risk tier / low confidence
    assert r.law_index_version == get_store().version


# ------------------------------------------------------------------ law sync + RAG
def test_law_sync_idempotent_then_simulated_amendment_reindexes():
    st = get_store()
    retr = get_retriever()
    v0 = st.version
    assert sync_now().changed is False and st.version == v0
    res = simulate_law_amendment("UK_DSIT")
    assert res.changed and res.new_version != v0 and res.changes[0].change == "ADDED"
    assert st.has_rule("UK_DSIT:SIM.Amendment-1")
    assert retr.indexed_version == st.version  # atomic re-index
    assert any(h.rule.rule_id == "UK_DSIT:SIM.Amendment-1" for h in retr.retrieve("simulated dsit sixth principle provenance", 3))
    assert sync_now().changed is False  # overlay persists, no new diff
    assert st.last_synced_at is not None


def test_seed_laws_cover_required_articles():
    st = get_store()
    for rid in ["EU_AI_ACT:Art.5", "EU_AI_ACT:Art.10", "EU_AI_ACT:Art.11", "EU_AI_ACT:Art.12", "EU_AI_ACT:Art.14",
                "EU_AI_ACT:Art.50", "EU_AI_ACT:Art.53", "UK_GDPR_ICO:Art.22", "UK_COPYRIGHT_TDM:CDPA.s29A"]:
        assert st.has_rule(rid)
    assert sum(r.rule_id.startswith("UK_DSIT:Principle.") for r in st.snapshot().values()) == 5
    assert st.has_rule("UK_GDPR_ICO:DUAA.ADM") and st.has_rule("UK_DSIT:Ofcom.OSA") and st.has_rule("EU_AI_ACT:AnnexIII")
    art50 = st.get("EU_AI_ACT:Art.50").text
    assert "2 August 2026" in art50 and "2 December 2026" in art50


def test_tier_a_applicability_and_tier_b_retrieval(fixtures_dir):
    prof = build_profile(build_index(fixtures_dir / "company_a_finscore"))
    app, na = build_checklist(prof)
    assert "HITL-01" in {c.check_id for c in app} and "SAFE-02" in {c.check_id for c in na}
    top = get_retriever().retrieve("machine-readable watermark for generated audio", 1)[0]
    assert top.rule.rule_id == "EU_AI_ACT:Art.50"


def test_scheduler_start_stop():
    from src.law_sync import start_scheduler, stop_scheduler
    from src.law_sync.scheduler import next_sync_at, scheduler_running

    start_scheduler(24)
    try:
        assert scheduler_running() and next_sync_at() is not None
    finally:
        stop_scheduler()
    assert not scheduler_running()


# ------------------------------------------------------------------ LLM client
def test_llm_client_offline_fallback():
    c = LLMClient(offline=True)
    assert c.structured("s", "u", Narrative, lambda: Narrative(summary="fallback")).summary == "fallback"


def test_llm_client_unreachable_server_falls_back():
    c = LLMClient(base_url="http://127.0.0.1:9/v1", offline=False, probe_timeout=0.3)
    assert c.available() is False
    assert c.structured("s", "u", Narrative, lambda: Narrative(summary="fb")).summary == "fb"


# ------------------------------------------------------------------ API
def test_api_endpoints(fixtures_dir, monkeypatch):
    from src.api import app
    from src.law_sync.linkup_scout import set_scout, LinkupRegulatoryScout

    # Disable live linkup web search during rapid API endpoint unit test
    set_scout(LinkupRegulatoryScout(api_key=None))
    try:
        client = TestClient(app)
        comps = client.get("/companies").json()
        assert {c["company_id"] for c in comps} == {"company_a_finscore", "company_b_voxgen", "company_c_medassist"}
        rep = client.post("/audit/run", json={"company_id": "company_a_finscore"}).json()
        assert rep["tenant_id"] == "company_a_finscore" and len(rep["confirmed_findings"]) >= 4 and rep["agent_execution_trace"]
        bad = client.post("/audit/run", json={"company_id": "company_a_finscore", "inject_fake_citation": True}).json()
        assert len(bad["quarantined_for_human_review"]) == 1
        assert client.post("/audit/run", json={"company_id": "nope"}).status_code == 404
        before = client.get("/laws/status").json()
        v0 = before["law_index_version"]
        assert client.post("/laws/sync").json()["changed"] is False
        sim = client.post("/laws/simulate-update", json={"jurisdiction": "EU_AI_ACT"}).json()
        assert sim["changed"] and sim["new_version"] != v0
        st = client.get("/laws/status").json()
        assert st["law_index_version"] == sim["new_version"] and st["rule_count"] == before["rule_count"] + 1
    finally:
        set_scout(None)


def test_eu_ai_act_only_scope(fixtures_dir, monkeypatch):
    monkeypatch.setenv("GRAPHITE_FRAMEWORKS", "EU_AI_ACT")
    rep = audit(fixtures_dir, "company_a_finscore")
    assert "EU AI Act" in rep.scope
    assert rep.all_findings()
    for f in rep.all_findings():
        assert f.primary_rule.startswith("EU_AI_ACT") or (f.check_id or "").startswith("OSS-"), f.primary_rule  # licence checks are regime-independent

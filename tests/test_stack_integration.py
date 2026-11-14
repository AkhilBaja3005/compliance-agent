"""Linkup / MongoDB Atlas / Databricks / connectors: live paths exercised with fakes, offline fallbacks verified."""
from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import httpx
import numpy as np
import pytest

from src.agents import run_audit, run_agents
from src.agents import tracing
from src.agents.llm_client import LLMClient, Narrative
from src.agents.oss_license_agent import LinkupLicenseVerifier
from src.connectors import github_connector as gh
from src.connectors.confluence_connector import ConfluenceCloudClient, scan_confluence_cloud, scan_local_confluence
from src.law_sync import get_store, set_scout, sync_now
from src.law_sync.linkup_scout import LinkupRegulatoryScout, clear_cache
from src.schemas import ComplianceFinding, TriagedAuditReport
from src.storage import DatabricksGovernanceSink, MongoComplianceStore, set_compliance_store
from src.storage.mongo_store import _MemCollection


# ------------------------------------------------------------------ fakes
class FakeLinkup:
    def __init__(self):
        self.queries = []

    def search(self, query, depth, output_type, **kw):
        assert depth in ("deep", "standard") and output_type == "sourcedAnswer"
        self.queries.append(query)
        slug = abs(hash(query)) % 10_000
        return SimpleNamespace(answer=f"Verified answer about: {query[:40]}",
                               sources=[SimpleNamespace(name="Official", url=f"https://eur-lex.example/doc/{slug}", snippet="official snippet text")])


class FakeCol(_MemCollection):
    def __init__(self):
        super().__init__(None)
        self.pipelines = []

    def aggregate(self, pipe):
        self.pipelines.append(pipe)
        vs = pipe[0]["$vectorSearch"]
        q = np.asarray(vs["queryVector"], dtype=np.float32)
        flt = vs.get("filter", {})
        docs = [d for d in self.docs if all(d.get(k) == v for k, v in flt.items())]
        scored = sorted(((float(np.dot(q, np.asarray(d["embedding"], dtype=np.float32))), d) for d in docs), key=lambda x: -x[0])
        return [{k: v for k, v in d.items() if k not in {"embedding", "_id"}} | {"score": sc} for sc, d in scored[: vs["limit"]]]


class FakeDB(dict):
    def __missing__(self, k):
        self[k] = FakeCol()
        return self[k]


class FakeMongoClient:
    def __init__(self):
        self.dbs: dict[str, FakeDB] = {}
        self.admin = SimpleNamespace(command=lambda *_a, **_k: {"ok": 1})

    def __getitem__(self, name):
        return self.dbs.setdefault(name, FakeDB())

    def close(self):
        pass


class FakeStatements:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def execute_statement(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise RuntimeError("warehouse down")
        return SimpleNamespace(status=SimpleNamespace(state="SUCCEEDED", error=None))


# ------------------------------------------------------------------ schemas
def test_report_and_finding_carry_every_contract_field(fixtures_dir):
    r = run_audit(fixtures_dir / "company_a_finscore", "company_a_finscore")
    for name in ("report_id", "company_name", "assessed_at", "scope", "rule_library_version", "input_coverage_pct",
                 "overall_readiness", "readiness_summary", "bundle_sha256", "stack_telemetry", "system_inventory",
                 "compliance_matrix", "confirmed_findings", "suspected_gaps", "quarantined_for_human_review", "passed_checks",
                 "eval_results", "fairness_metrics", "roadmap", "input_coverage", "agent_execution_trace"):
        assert name in TriagedAuditReport.model_fields
    assert set(r.stack_telemetry) >= {"databricks_endpoint", "unity_catalog_table", "mlflow_trace_id", "mongodb_database",
                                      "mongodb_checkpoint_id", "linkup_sources_verified_count"}
    for name in ("finding_id", "severity", "status", "due_date", "days_remaining", "confidence", "title", "system_id", "system_name",
                 "primary_rule", "also_engages", "summary", "code_vs_doc_drift", "evidence", "exposure_text", "owner", "effort_days",
                 "human_review_required", "remediation_steps", "related_ids", "history_status", "first_seen_at", "linkup_citation_urls"):
        assert name in ComplianceFinding.model_fields
    f = next(x for x in r.confirmed_findings if x.check_id == "HITL-01")
    assert f.severity == "High" and f.system_id == "S1" and f.owner and f.remediation_steps and f.due_date and f.primary_rule == f.regulatory_reference
    assert f.confidence == f.confidence_score and f.evidence[0].type == f.evidence[0].source_type and f.evidence[0].item == f.evidence[0].artifact_id
    assert r.report_id.startswith("AEGIS-") and len(r.bundle_sha256) == 64 and r.assessed_at
    assert r.system_inventory and r.system_inventory[0].system_id == "S1" and r.system_inventory[0].detected_in_code
    assert r.compliance_matrix and r.roadmap and r.fairness_metrics["status"] in {"SUSPECTED_GAP", "DOCUMENTED", "NOT_APPLICABLE"}
    assert r.input_coverage_pct == 75.0 and r.overall_readiness == "NOT_READY"
    assert r.eval_results["resolution_pct"] == 100.0
    # offline: honest telemetry, no fabricated engine ids
    assert r.stack_telemetry["unity_catalog_table"] is None and r.stack_telemetry["mongodb_database"] is None
    assert r.stack_telemetry["engines"]["mongodb"] in ("in-memory-fallback", "live") and r.stack_telemetry["engines"]["linkup"] in ("disabled", "live")


def test_bundle_hash_is_deterministic(fixtures_dir):
    a = run_audit(fixtures_dir / "company_c_medassist", "company_c_medassist")
    b = run_audit(fixtures_dir / "company_c_medassist", "company_c_medassist")
    assert a.bundle_sha256 == b.bundle_sha256 and a.report_id != b.report_id


# ------------------------------------------------------------------ connectors
def test_github_local_connector_stamps_commit_sha(tmp_path, fixtures_dir):
    repo = tmp_path / "repo"
    (repo / "app").mkdir(parents=True)
    (repo / "app" / "main.py").write_text((fixtures_dir / "company_a_finscore/app/main.py").read_text())
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"], cwd=repo, check=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    scan = gh.scan_github_source(repo, "t1")
    assert scan.commit_sha == head and not scan.cloned
    assert scan.result.slices and all(s.commit_sha == head for s in scan.result.slices)
    assert all(c.commit_sha == head for c in scan.result.cards) and scan.result.slices[0].locator.startswith("app/main.py:")
    plain = gh.scan_github_source(fixtures_dir / "company_a_finscore", "t1")  # not a git root -> deterministic tree hash
    assert plain.commit_sha.startswith("local-")


def test_github_url_is_shallow_cloned_with_token_and_deleted(monkeypatch, fixtures_dir):
    calls, seen = [], {}

    def fake_git(args, cwd=None, env=None, timeout=180):
        calls.append(args)
        if args[0] == "clone":
            dest = Path(args[-1])
            seen["dest"] = dest
            seen["env"] = env
            import shutil

            shutil.copytree(fixtures_dir / "company_b_voxgen", dest)
            return ""
        return "deadbeef" * 5

    monkeypatch.setattr(gh, "_git", fake_git)
    scan = gh.scan_github_source("https://github.com/acme/voxgen", "tb", token="ghp_secrettoken")
    assert scan.cloned and scan.commit_sha == "deadbeef" * 5 and scan.origin == "github:https://github.com/acme/voxgen"
    assert "--depth" in calls[0] and "1" in calls[0] and all("ghp_secrettoken" not in a for a in calls[0])  # token never in argv
    assert "http.https://github.com/.extraheader" in seen["env"]["GIT_CONFIG_KEY_0"]
    assert not seen["dest"].exists() and not seen["dest"].parent.exists()  # temp clone removed
    assert any(s.is_generation for s in scan.result.slices) and all(s.commit_sha == "deadbeef" * 5 for s in scan.result.slices)
    assert gh.is_github_url("https://github.com/o/r") and not gh.is_github_url("./local/dir")
    with pytest.raises(FileNotFoundError):
        gh.scan_github_source("/no/such/dir", "t")


XHTML = """<h1>AI Systems</h1><p>S1: Credit Scorer - scores loan applicants</p><p>S2: Support Bot - answers customers</p>
<h2>Data Protection</h2><p>All personal data such as names and emails is masked before leaving our systems.</p>
<h2>Hosting</h2><p>All inference is hosted exclusively in EU regions.</p>
<table><tr><td>S3</td><td>Fraud Model</td><td>flags fraud</td></tr></table>"""


def test_confluence_local_xhtml_and_markdown(tmp_path):
    (tmp_path / "page.xhtml").write_text(XHTML)
    (tmp_path / "gov.md").write_text("# Oversight\nEvery decision is reviewed and approved by a human underwriter before release.\n")
    scan = scan_local_confluence(tmp_path, "tc")
    assert scan.pages == 2 and any(c.section_header == "Hosting" for c in scan.chunks)
    assert {s.system_id for s in scan.systems} >= {"S1", "S2"}
    assert next(s for s in scan.systems if s.system_id == "S1").name.startswith("Credit Scorer")
    assert {a.claim_type for a in scan.assertions} >= {"PRIVACY", "HOSTING", "HITL"}


def test_confluence_cloud_rest_v2(monkeypatch):
    pages = {"results": [{"id": "1", "title": "Policy", "body": {"storage": {"value": XHTML}}}], "_links": {}}

    def handler(request: httpx.Request):
        assert request.headers["authorization"].startswith("Basic ")
        if request.url.path.endswith("/api/v2/spaces"):
            assert request.url.params["keys"] == "AIGOV"
            return httpx.Response(200, json={"results": [{"id": "42"}]})
        if request.url.path.endswith("/spaces/42/pages"):
            assert request.url.params["body-format"] == "storage"
            return httpx.Response(200, json=pages)
        return httpx.Response(404)

    http = httpx.Client(auth=("a@b.c", "tok"), transport=httpx.MockTransport(handler))
    client = ConfluenceCloudClient("https://acme.atlassian.net", "a@b.c", "tok", client=http)
    scan = scan_confluence_cloud("tc", "AIGOV", client=client)
    assert scan.origin == "confluence-cloud:AIGOV" and scan.pages == 1
    assert scan.chunks[0].doc_name == "confluence/AIGOV/Policy" and {s.system_id for s in scan.systems} >= {"S1", "S2"}
    with pytest.raises(ValueError):
        scan_confluence_cloud("tc", "AIGOV")  # no creds, no client


def test_connector_layout_github_confluence_subfolders(tmp_path, fixtures_dir):
    import shutil

    from src.edge_extractors import build_index

    root = tmp_path / "company_z_demo"
    shutil.copytree(fixtures_dir / "company_a_finscore" / "app", root / "github" / "app")
    (root / "confluence").mkdir(parents=True)
    (root / "confluence" / "p.xhtml").write_text(XHTML.replace("S1: Credit Scorer", "S1: Score Applicant"))
    ix = build_index(root)
    assert ix.slices and ix.chunks and ix.code_origin.startswith("local:") and ix.docs_origin.startswith("local:")
    s1 = next(s for s in ix.systems if s.system_id == "S1")
    assert s1.declared_in_docs and s1.detected_in_code and s1.hosting_regions == ["US"]


# ------------------------------------------------------------------ Linkup
def test_linkup_scout_attaches_source_url_to_every_rule(monkeypatch):
    clear_cache()
    fake = FakeLinkup()
    set_scout(LinkupRegulatoryScout(client=fake))
    v0 = get_store().version
    res = sync_now()
    rules = get_store().snapshot().values()
    assert all(r.linkup_source_url and r.linkup_snippet and r.linkup_verified_at for r in rules)
    assert len(fake.queries) == len(rules) and any("2 December 2026" in q for q in fake.queries)
    assert res.changed is False and get_store().version == v0  # provenance metadata never bumps the rule version
    assert "+linkup" in res.source


def test_linkup_disabled_and_failures_degrade_silently():
    scout = LinkupRegulatoryScout(api_key="")
    assert not scout.enabled and scout.enrich(get_store().snapshot()) == get_store().snapshot()

    class Boom:
        def search(self, **kw):
            raise RuntimeError("quota")

    clear_cache()
    s = LinkupRegulatoryScout(client=Boom())
    out = s.enrich(get_store().snapshot())
    assert all(r.linkup_source_url is None for r in out.values()) and s.errors > 0


def test_linkup_license_verifier_cites_gpl_and_ncl_findings(fixtures_dir):
    fake = FakeLinkup()
    r = run_audit(fixtures_dir / "company_b_voxgen", "company_b_voxgen", linkup=LinkupLicenseVerifier(client=fake))
    oss = {f.check_id: f for f in r.confirmed_findings if f.check_id.startswith("OSS")}
    assert set(oss) == {"OSS-01", "OSS-02"}
    assert any("GPL-3.0" in q and "pyqt5" in q for q in fake.queries) and any("CC-BY-NC-4.0" in q for q in fake.queries)
    for f in oss.values():
        assert f.linkup_citation_urls and all(u.startswith("https://eur-lex.example") for u in f.linkup_citation_urls)
        assert all(e.source_url and e.linkup_snippet for e in f.evidence)
    assert r.stack_telemetry["linkup_sources_verified_count"] >= 2
    assert not [f for f in r.quarantined_for_human_review]  # Linkup metadata does not disturb Gate 1


# ------------------------------------------------------------------ MongoDB Atlas
def atlas():
    store = MongoComplianceStore(client=FakeMongoClient(), db_name="aegis_test")
    set_compliance_store(store)
    return store


def test_mongo_store_vector_search_history_and_checkpointer(fixtures_dir):
    store = atlas()
    assert store.is_atlas and store.describe() == {"mode": "atlas", "database": "aegis_test", "error": None}
    r1 = run_audit(fixtures_dir / "company_a_finscore", "company_a_finscore", compliance_store=store)
    assert r1.stack_telemetry["mongodb_database"] == "aegis_test" and r1.stack_telemetry["engines"]["mongodb"] == "atlas"
    assert {f.history_status for f in r1.confirmed_findings} == {"NEW"} and all(f.first_seen_at for f in r1.confirmed_findings)
    first = {f.finding_id: f.first_seen_at for f in r1.confirmed_findings}
    # $vectorSearch ran against the Atlas-style collections
    rules = store.search_rules("machine-readable watermark generated content", k=3)
    assert rules and rules[0][0] == "EU_AI_ACT:Art.50"
    assert store.db["regulatory_rules"].pipelines and "$vectorSearch" in store.db["regulatory_rules"].pipelines[-1][0]
    arts = store.search_artifacts("company_a_finscore", "human approval of credit decisions", k=2)
    assert arts and all(a["tenant_id"] == "company_a_finscore" for a in arts)
    assert store.search_artifacts("company_c_medassist", "anything") == []  # tenant isolation
    # second run: same findings are RECURRING with the original first_seen_at
    r2 = run_audit(fixtures_dir / "company_a_finscore", "company_a_finscore", compliance_store=store)
    assert {f.history_status for f in r2.confirmed_findings} == {"RECURRING"}
    assert {f.finding_id: f.first_seen_at for f in r2.confirmed_findings} == first
    # retriever primary path is Atlas
    from src.regulatory_rag import get_retriever

    assert get_retriever().retrieve("machine-readable watermark generated content", 1)[0].rule.rule_id == "EU_AI_ACT:Art.50"


def test_history_resolved_when_check_starts_passing():
    store = MongoComplianceStore()  # in-memory fallback implements the same history semantics

    def f(status):
        return ComplianceFinding(finding_id="x-PII-01", tenant_id="x", jurisdiction="EU_AI_ACT", regulatory_reference="EU_AI_ACT:Art.10",
                                 risk_tier="HIGH_RISK", status=status, confidence_score=0.9, title="t", summary="s")

    a, _ = store.apply_history("Acme", [f("CONFIRMED_VIOLATION")])
    b, _ = store.apply_history("Acme", [f("CONFIRMED_VIOLATION")])
    c, resolved = store.apply_history("Acme", [f("PASS")])
    assert (a[0].history_status, b[0].history_status, c[0].history_status) == ("NEW", "RECURRING", "RESOLVED")
    assert b[0].first_seen_at == a[0].first_seen_at == c[0].first_seen_at and resolved == ["x-PII-01"]
    _, gone = store.apply_history("Acme", [f("SUSPECTED_GAP")])  # re-opens
    _, gone2 = store.apply_history("Acme", [])  # no longer raised at all -> resolved
    assert gone == [] and gone2 == ["x-PII-01"]


def test_mongo_unreachable_falls_back_and_history_file_persists(tmp_path, monkeypatch):
    monkeypatch.setenv("MONGODB_TIMEOUT_MS", "200")
    store = MongoComplianceStore(uri="mongodb://127.0.0.1:1")
    assert not store.is_atlas and store.error and store.search_rules("q") is None
    saver, kind = store.checkpointer()
    assert kind == "memory"
    monkeypatch.setenv("AEGIS_HISTORY_FILE", str(tmp_path / "hist.json"))
    s1 = MongoComplianceStore()
    f = ComplianceFinding(finding_id="y-1", tenant_id="y", jurisdiction="EU_AI_ACT", regulatory_reference="EU_AI_ACT:Art.10",
                          risk_tier="HIGH_RISK", status="SUSPECTED_GAP", confidence_score=0.9, title="t", summary="s")
    s1.apply_history("Acme", [f])
    out, _ = MongoComplianceStore().apply_history("Acme", [f])  # new process, same file
    assert out[0].history_status == "RECURRING"


def test_supervisor_checkpoints_every_run(fixtures_dir):
    run = run_agents(fixtures_dir / "company_c_medassist", "company_c_medassist")
    assert run.checkpoint_id and run.checkpointer_kind == "memory"


# ------------------------------------------------------------------ Databricks
def _db_env(monkeypatch, endpoint="databricks-meta-llama-3-3-70b-instruct"):
    monkeypatch.setenv("DATABRICKS_HOST", "https://dbc-123.cloud.databricks.com/")
    monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-test")
    monkeypatch.setenv("DATABRICKS_SERVING_ENDPOINT", endpoint)
    monkeypatch.setenv("BYOM_OFFLINE", "false")


def test_databricks_serving_no_response_format_and_json_retry(monkeypatch):
    _db_env(monkeypatch)
    seen = []
    replies = ["Sure! here you go", "```json\n{\"nope\": 1}\n```", "```json\n{\"summary\": \"clean summary\"}\n```"]

    def handler(req: httpx.Request):
        body = json.loads(req.content)
        seen.append((str(req.url), req.headers["authorization"], body))
        return httpx.Response(200, json={"choices": [{"message": {"content": replies[len(seen) - 1]}}]})

    c = LLMClient(http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert c.databricks_endpoint == "databricks-meta-llama-3-3-70b-instruct" and c.available()
    out = c.structured("sys", "user", Narrative, lambda: Narrative(summary="FALLBACK"))
    assert out.summary == "clean summary" and len(seen) == 3  # two validation retries then success
    url, auth, body = seen[0]
    assert url == "https://dbc-123.cloud.databricks.com/serving-endpoints/databricks-meta-llama-3-3-70b-instruct/invocations"
    assert auth == "Bearer dapi-test" and "response_format" not in body and "JSON" in body["messages"][0]["content"]
    assert body["messages"][-1]["role"] == "user" and "corrected JSON" in seen[2][2]["messages"][-1]["content"]


def test_databricks_serving_http_error_falls_back(monkeypatch):
    _db_env(monkeypatch, "databricks-claude-sonnet-4-5")
    c = LLMClient(http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    assert c.structured("s", "u", Narrative, lambda: Narrative(summary="fb")).summary == "fb"
    bad = LLMClient(http=httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "never json"}}]}))))
    assert bad.structured("s", "u", Narrative, lambda: Narrative(summary="fb2")).summary == "fb2"


def test_unity_catalog_sink_writes_report_and_inventory(fixtures_dir):
    stm = FakeStatements()
    sink = DatabricksGovernanceSink(host="h", token="t", warehouse_id="wh1", client=SimpleNamespace(statement_execution=stm))
    r = run_audit(fixtures_dir / "company_a_finscore", "company_a_finscore", sink=sink)
    assert r.stack_telemetry["unity_catalog_table"] == "compliance_catalog.audit_prod.audit_reports"
    sql = [c["statement"] for c in stm.calls]
    assert any("CREATE TABLE IF NOT EXISTS compliance_catalog.audit_prod.audit_reports" in s and "USING DELTA" in s for s in sql)
    assert any("INSERT INTO compliance_catalog.audit_prod.ai_system_inventory" in s for s in sql)
    insert = next(c for c in stm.calls if "INSERT INTO compliance_catalog.audit_prod.audit_reports" in c["statement"])
    params = {p.name: p.value for p in insert["parameters"]}
    assert insert["warehouse_id"] == "wh1" and params["report_id"] == r.report_id and json.loads(params["report_json"])["tenant_id"] == "company_a_finscore"
    assert r.stack_telemetry["engines"]["unity_catalog"] == "live"


def test_unity_catalog_sink_disabled_or_failing_never_breaks_audit(fixtures_dir):
    assert DatabricksGovernanceSink().persist.__self__.enabled is False
    bad = DatabricksGovernanceSink(host="h", token="t", warehouse_id="wh", client=SimpleNamespace(statement_execution=FakeStatements(fail=True)))
    r = run_audit(fixtures_dir / "company_c_medassist", "company_c_medassist", sink=bad)
    assert r.stack_telemetry["unity_catalog_table"] is None and "error" in r.stack_telemetry["engines"]["unity_catalog"]


def test_mlflow_tracing_noop_by_default_and_live_when_configured(monkeypatch, fixtures_dir):
    from src.agents.supervisor import AGENTS, SupervisorAgent

    assert getattr(SupervisorAgent.run, "__wrapped_traced__", False)
    assert all(getattr(a.evaluate, "__wrapped_traced__", False) for a in AGENTS.values()) and len(AGENTS) == 6
    assert run_audit(fixtures_dir / "company_c_medassist", "company_c_medassist").stack_telemetry["mlflow_trace_id"] is None

    names, state = [], {"active": None}
    fake = types.ModuleType("mlflow")
    fake.set_tracking_uri = lambda uri: None
    fake.set_experiment = lambda e: None

    def trace(name=None, span_type=None):
        def deco(fn):
            def wrapper(*a, **k):
                names.append(name)
                top = state["active"] is None
                if top:
                    state["active"] = SimpleNamespace(trace_id="tr-abc123")
                try:
                    return fn(*a, **k)
                finally:
                    if top:
                        state["active"] = None
            return wrapper
        return deco

    fake.trace = trace
    fake.get_current_active_span = lambda: state["active"]
    monkeypatch.setitem(sys.modules, "mlflow", fake)
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "databricks")
    monkeypatch.setattr(tracing, "_configured", False)
    r = run_audit(fixtures_dir / "company_c_medassist", "company_c_medassist")
    assert r.stack_telemetry["mlflow_trace_id"] == "tr-abc123" and r.stack_telemetry["engines"]["mlflow_tracing"] == "live"
    assert "SupervisorAgent.run" in names
    assert {f"{a}_agent.evaluate" for a in ("pii_flow", "hitl_oversight", "safety_watermark", "oss_license", "dpa_provenance", "code_doc_drift")} <= set(names)


# ------------------------------------------------------------------ everything live at once + API
def test_all_three_engines_live_together(fixtures_dir, monkeypatch):
    clear_cache()
    set_scout(LinkupRegulatoryScout(client=FakeLinkup()))
    sync_now()
    _db_env(monkeypatch)
    store = atlas()
    stm = FakeStatements()
    sink = DatabricksGovernanceSink(host="h", token="t", warehouse_id="wh", client=SimpleNamespace(statement_execution=stm))
    handler = lambda req: httpx.Response(200, json={"choices": [{"message": {"content": "{\"summary\": \"polished\"}"}}]})
    llm = LLMClient(http=httpx.Client(transport=httpx.MockTransport(handler)))
    r = run_audit(fixtures_dir / "company_b_voxgen", "company_b_voxgen", llm=llm, linkup=LinkupLicenseVerifier(client=FakeLinkup()),
                  compliance_store=store, sink=sink)
    t = r.stack_telemetry
    assert t["databricks_endpoint"] == "databricks-meta-llama-3-3-70b-instruct" and t["unity_catalog_table"].endswith("audit_reports")
    assert t["mongodb_database"] == "aegis_test" and t["linkup_sources_verified_count"] >= 2
    assert all(f.summary.startswith("polished") or "polished" in f.summary for f in r.all_findings())  # LLM narrative applied, status untouched
    assert {f.check_id for f in r.confirmed_findings} >= {"SAFE-01", "SAFE-02", "OSS-01", "OSS-02"}
    assert all(u for f in r.confirmed_findings for u in f.linkup_citation_urls[:1])


def test_api_stack_status_and_connector_options(fixtures_dir, monkeypatch):
    from fastapi.testclient import TestClient

    from src.api import app

    c = TestClient(app)
    st = c.get("/stack/status").json()
    assert (st["linkup"].startswith("disabled") or st["linkup"].startswith("live")) and st["mongodb"]["mode"] in ("memory", "live-atlas") and st["databricks_model_serving"] in ("offline-fallback", "anthropic-claude-direct", "live")
    rep = c.post("/audit/run", json={"company_id": "company_c_medassist", "github_url": str(fixtures_dir / "company_c_medassist")}).json()
    assert rep["report_id"].startswith("AEGIS-")


def test_search_rules_ignores_pdf_chunks_without_rule_id():
    """PDF chunks live in the same collection as statutory rules; a vector hit without rule_id must not break rule retrieval."""
    from src.storage.mongo_store import MongoComplianceStore

    class Coll:
        def aggregate(self, pipe):
            return [{"score": 0.9}, {"rule_id": "EU_AI_ACT:Art.5", "score": 0.8}, {"rule_id": "EU_AI_ACT:Art.14", "score": 0.7}]

    store = MongoComplianceStore.__new__(MongoComplianceStore)
    store.is_atlas = True
    store.embed = lambda texts: [[0.0] * 4 for _ in texts]
    store.db = {"regulatory_rules": Coll()}
    assert store.search_rules("q", 2) == [("EU_AI_ACT:Art.5", 0.8), ("EU_AI_ACT:Art.14", 0.7)]

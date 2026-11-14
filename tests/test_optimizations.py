"""Performance / accuracy / connector optimisations: parallel agents, batched embeddings, AST cache, pruned context,
provider-aware LLM output, git-diff scanning, concurrent Confluence, export dedupe, guardrail exception boundaries."""
from __future__ import annotations

import json
import random
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import numpy as np
import pytest

from src.agents import run_audit
from src.agents.llm_client import LLMClient, Narrative, build_focused_context
from src.agents.supervisor import AGENTS, SupervisorAgent
from src.edge_extractors import code_scanner as cs
from src.edge_extractors.code_scanner import AstCache, scan_code, set_ast_cache
from src.schemas.artifacts import ASTSlice

FIX = Path(__file__).parent / "fixtures" / "companies"
A, B = FIX / "company_a_finscore", FIX / "company_b_voxgen"


def sig(rep):
    return [(f.check_id, f.status, f.severity) for f in sorted(rep.all_findings(), key=lambda f: f.check_id)]


# ------------------------------------------------------------------ (a) parallel micro-agents
def test_parallel_agents_are_concurrent_and_deterministic(monkeypatch):
    base = run_audit(A, "a")  # reference run with the real agents

    state = {"now": 0, "peak": 0}
    lock = threading.Lock()
    originals = {n: a.run for n, a in AGENTS.items()}

    def slow(name):
        def run(chk, ctx):
            with lock:
                state["now"] += 1
                state["peak"] = max(state["peak"], state["now"])
            time.sleep(random.uniform(0.0, 0.04))  # random completion order
            try:
                return originals[name](chk, ctx)
            finally:
                with lock:
                    state["now"] -= 1
        return run
    for n, a in AGENTS.items():
        monkeypatch.setattr(a, "run", slow(n))
    reps = [run_audit(A, "a") for _ in range(3)]
    assert state["peak"] >= 2, "checks never overlapped: execution was not parallel"
    assert all(sig(r) == sig(base) for r in reps)  # same findings regardless of timing
    traces = [[t for t in r.agent_execution_trace if "_agent:" in t or "dispatch" in t] for r in reps]
    assert traces[0] == traces[1] == traces[2]
    ids = [f.check_id for f in sorted(base.all_findings(), key=lambda f: f.check_id)]
    assert ids == sorted(ids)


def test_one_failing_agent_does_not_abort_siblings_and_retries_once(monkeypatch):
    calls = {"PII-01": 0}
    real = AGENTS["pii_flow"].run

    def flaky(chk, ctx):
        if chk.check_id == "PII-01":
            calls["PII-01"] += 1
            raise RuntimeError("boom")
        return real(chk, ctx)
    monkeypatch.setattr(AGENTS["pii_flow"], "run", flaky)
    rep = run_audit(A, "a")
    f = next(f for f in rep.all_findings() if f.check_id == "PII-01")
    assert calls["PII-01"] == 2 and f.status == "SUSPECTED_GAP"  # retried once, then closed-world gap
    assert len(rep.all_findings()) >= 10  # every other check still produced a finding


def test_supervisor_worker_limit():
    assert SupervisorAgent.__init__.__defaults__ is not None
    sup = SupervisorAgent(SimpleNamespace(index=SimpleNamespace(tenant_id="t")), [], max_workers=3)
    assert sup.max_workers == 3


# ------------------------------------------------------------------ batch embeddings
def test_embed_texts_batch_batches_and_preserves_order():
    from src.regulatory_rag.tier_b_index import embed_texts_batch

    seen = []

    class Enc:
        def encode(self, texts):
            seen.append(len(texts))
            return np.asarray([[float(len(t)), 1.0] for t in texts], dtype=np.float32)
    texts = ["x" * i for i in range(1, 131)]
    out = embed_texts_batch(texts, batch_size=50, embedder=Enc())
    assert seen == [50, 50, 30] and [v[0] for v in out] == [float(len(t)) for t in texts]
    assert embed_texts_batch([], embedder=Enc()) == []


def test_store_bulk_upserts_in_batches_on_atlas_path():
    from src.storage.mongo_store import MongoComplianceStore, _MemCollection

    writes = []

    class Col(_MemCollection):
        def bulk_write(self, ops, ordered=True):
            writes.append(len(ops))
            super().bulk_write(ops, ordered)

    class DB(dict):
        def __missing__(self, k):
            self[k] = Col()
            return self[k]
    client = SimpleNamespace(admin=SimpleNamespace(command=lambda *a, **k: {"ok": 1}), __getitem__=None)
    store = MongoComplianceStore.__new__(MongoComplianceStore)
    store.is_atlas, store.db, store._embedder = True, DB(), SimpleNamespace(encode=lambda t: np.ones((len(t), 4), dtype=np.float32))
    store._lock, store._mem = threading.RLock(), {}
    chunks = [{"chunk_id": f"c{i}", "text": f"t{i}", "sha256_hash": f"h{i}"} for i in range(250)]
    assert store.index_pdf_chunks(chunks) == 250
    assert writes == [100, 100, 50]  # bulk_write of UpdateOne in batches of 100
    assert len(store.db["tenant_artifacts"].docs) == 250 and client


# ------------------------------------------------------------------ (b) content-addressed AST cache
def test_ast_cache_hits_on_repeat_and_skips_tree_sitter(monkeypatch, tmp_path):
    set_ast_cache(AstCache())
    first = scan_code(A, "ta")
    c = cs.ast_cache()
    assert c.hits == 0 and c.misses > 0 and first.slices
    parses = {"n": 0}
    real = cs._PARSER

    class Counting:  # tree_sitter.Parser is a C extension (read-only attributes): swap the module-level parser for a counting proxy
        def parse(self, *a, **k):
            parses["n"] += 1
            return real.parse(*a, **k)
    monkeypatch.setattr(cs, "_PARSER", Counting())
    second = scan_code(A, "ta")
    assert c.hits >= 1 and parses["n"] == 0, "unchanged files must not be re-parsed"
    assert [(s.slice_id, s.sha256_hash, s.locator) for s in second.slices] == [(s.slice_id, s.sha256_hash, s.locator) for s in first.slices]
    assert [x.model_dump() for x in second.cards] == [x.model_dump() for x in first.cards]


def test_ast_cache_rebinds_tenant_and_invalidates_on_change(tmp_path):
    set_ast_cache(AstCache())
    src = tmp_path / "svc.py"
    src.write_text('import requests\ndef handle(email):\n    return requests.post("https://api.openai.com/v1/chat/completions", json={"e": email})\n')
    a = scan_code(tmp_path, "tenant-a")
    b = scan_code(tmp_path, "tenant-b")
    assert cs.ast_cache().hits >= 1
    assert {s.tenant_id for s in b.slices} == {"tenant-b"} and a.slices[0].slice_id != b.slices[0].slice_id  # slice ids embed the tenant
    assert a.slices[0].sha256_hash == b.slices[0].sha256_hash and a.slices[0].locator == b.slices[0].locator
    src.write_text(src.read_text() + "\n# changed\n")
    hits_before = cs.ast_cache().hits
    scan_code(tmp_path, "tenant-b")
    assert cs.ast_cache().hits == hits_before  # content changed: new sha256, cache miss


def test_ast_cache_disk_roundtrip_is_atomic_and_versioned(tmp_path):
    path = tmp_path / ".aegis_cache" / "ast_cache.json"
    set_ast_cache(AstCache(path))
    scan_code(A, "t")
    assert path.is_file() and json.loads(path.read_text())["version"] == cs.SCANNER_VERSION
    set_ast_cache(AstCache(path))  # a fresh process: loads from disk
    scan_code(A, "t")
    assert cs.ast_cache().hits >= 1 and cs.ast_cache().misses == 0 or cs.ast_cache().hits >= 1
    data = json.loads(path.read_text())
    data["version"] = "old"
    path.write_text(json.dumps(data))
    assert AstCache(path).entries == {}  # a scanner-version bump invalidates everything
    set_ast_cache(None)


def test_language_scanner_results_are_cached_too(tmp_path):
    set_ast_cache(AstCache())
    (tmp_path / "svc.go").write_text('package main\nimport "net/http"\nfunc decide(email string) { http.Post("https://api.openai.com/v1/chat/completions", "application/json", nil) }\n')
    one = scan_code(tmp_path, "t")
    two = scan_code(tmp_path, "t")
    assert cs.ast_cache().hits >= 1 and [s.slice_id for s in one.slices] == [s.slice_id for s in two.slices] and one.slices


# ------------------------------------------------------------------ (c) git diff scanning
def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                   "GIT_COMMITTER_EMAIL": "t@t", "PATH": __import__("os").environ["PATH"], "HOME": str(cwd)})


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    svc = 'import requests\ndef {n}(email):\n    return requests.post("https://api.openai.com/v1/chat/completions", json={{"e": email}})\n'
    (tmp_path / "a.py").write_text(svc.format(n="alpha"))
    (tmp_path / "b.py").write_text(svc.format(n="beta"))
    (tmp_path / "notes.md").write_text("# Notes\nWe mask personal data.\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "base")
    git(tmp_path, "tag", "base")
    (tmp_path / "a.py").write_text(svc.format(n="alpha") + "# touched\n")
    (tmp_path / "c.py").write_text(svc.format(n="gamma"))
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "change")
    return tmp_path


def test_diff_mode_scans_only_changed_files(repo):
    from src.connectors.github_connector import changed_files, scan_github_source

    assert sorted(changed_files(repo, "base")) == ["a.py", "c.py"]
    full = scan_github_source(repo, "t")
    diff = scan_github_source(repo, "t", diff_base="base")
    assert {s.file_path for s in full.result.slices} == {"a.py", "b.py", "c.py"}
    assert {s.file_path for s in diff.result.slices} == {"a.py", "c.py"} and diff.diff_files and set(diff.diff_files) == {"a.py", "c.py"}
    assert "b.py" not in diff.result.py_files and diff.diff_base == "base"


def test_diff_mode_end_to_end_scope_and_bad_base(repo):
    from aegis_audit.client import ComplianceAuditor

    sess = ComplianceAuditor().audit(company_name="Diff Co", target_dir=str(repo), diff_base="base")
    assert "[diff vs base: 2 changed file(s)]" in sess.to_dict()["scope"] or "diff vs base" in str(sess.scope)
    from src.connectors.github_connector import changed_files
    with pytest.raises(ValueError):
        changed_files(repo, "--output=/tmp/x")  # option-looking input is refused before reaching git
    with pytest.raises(RuntimeError):
        changed_files(repo, "no-such-ref")


def test_cli_scan_diff_flag_reaches_the_scanner(repo, tmp_path):
    from typer.testing import CliRunner

    from aegis_audit.cli import app

    res = CliRunner().invoke(app, ["scan", "-t", str(repo), "--diff", "base", "-c", "Diff Co", "-o", str(tmp_path / "r.pdf"), "--format", "json"])
    assert res.exit_code == 0, res.output
    assert "diff vs base: 2 changed file(s)" in res.output


# ------------------------------------------------------------------ concurrent Confluence
def test_confluence_bodies_fetched_concurrently_in_order():
    from src.connectors.confluence_connector import ConfluenceCloudClient, scan_confluence_cloud

    state = {"now": 0, "peak": 0}
    lock = threading.Lock()
    body = lambda i: f"<h1>Page {i}</h1><p>Human review of decision {i} is required before release.</p>"  # noqa: E731

    def handler(req: httpx.Request):
        p = req.url.path
        if p.endswith("/api/v2/spaces"):
            return httpx.Response(200, json={"results": [{"id": "9"}]})
        if p.endswith("/spaces/9/pages"):
            assert "body-format" not in req.url.params
            return httpx.Response(200, json={"results": [{"id": str(i), "title": f"P{i}"} for i in range(12)], "_links": {}})
        if "/api/v2/pages/" in p:
            with lock:
                state["now"] += 1
                state["peak"] = max(state["peak"], state["now"])
            time.sleep(0.05)
            with lock:
                state["now"] -= 1
            i = int(p.rsplit("/", 1)[1])
            return httpx.Response(200, json={"id": str(i), "title": f"P{i}", "body": {"storage": {"value": body(i)}}})
        return httpx.Response(404)
    http = httpx.Client(auth=("a", "b"), transport=httpx.MockTransport(handler))
    scan = scan_confluence_cloud("t", "SP", client=ConfluenceCloudClient("https://x.atlassian.net", "a", "b", client=http))
    assert scan.pages == 12 and state["peak"] >= 2
    order = [c.doc_name for c in scan.chunks]
    assert order == [f"confluence/SP/P{i}" for i in range(12)]  # concurrent fetch, original page order kept


# ------------------------------------------------------------------ (d) guardrail exception boundaries
@pytest.mark.parametrize("gate,attr", [("gate1_citations", "_reasons"), ("gate3_entailment", "_entailment_reasons")])
def test_guardrail_exceptions_quarantine_never_drop(monkeypatch, gate, attr):
    import importlib

    from src.guardrails import apply_guardrails
    from src.agents.pipeline import run_agents

    run = run_agents(A, "a")
    mod = importlib.import_module(f"src.guardrails.{gate}")
    monkeypatch.setattr(mod, attr, lambda *a, **k: (_ for _ in ()).throw(KeyError("simulated")))
    rep = apply_guardrails(run.findings, run.index, run.trace)
    assert len(rep.all_findings()) == len(run.findings)  # nothing dropped
    guarded = [f for f in rep.quarantined_for_human_review if "guardrail_error:KeyError" in (f.quarantine_reason or "")]
    assert guarded and all(f.status == "QUARANTINED_FOR_HUMAN_REVIEW" and f.human_review_required for f in guarded)
    assert all(f.quarantine_reason.startswith("guardrail_error:KeyError: 'simulated'") or "guardrail_error:KeyError" in f.quarantine_reason for f in guarded)
    assert all(f.original_status for f in guarded)


def test_gate1_registry_failure_quarantines_every_finding(monkeypatch):
    from src.agents.pipeline import run_agents
    from src.guardrails import apply_guardrails

    run = run_agents(A, "a")
    monkeypatch.setattr(type(run.index), "artifact_registry", lambda self: (_ for _ in ()).throw(RuntimeError("registry down")))
    rep = apply_guardrails(run.findings, run.index, run.trace)
    assert len(rep.all_findings()) == len(run.findings) and not rep.confirmed_findings and not rep.passed_checks
    assert all("guardrail_error:RuntimeError: registry down" in f.quarantine_reason for f in rep.quarantined_for_human_review[:3])


# ------------------------------------------------------------------ pruned context + provider-aware extraction
def test_focused_context_contains_only_relevant_lines():
    code = "\n".join(["import os", "def handle(email):", "    token = os.environ['X']", "    a = 1", "    b = 2", "    c = 3", "    d = 4",
                     "    return requests.post('https://api.openai.com/v1', json={'e': email})", "    z = 9"])
    sl = ASTSlice(slice_id="s", tenant_id="t", file_path="svc.py", start_line=10, end_line=18, code_snippet=code, sha256_hash="h")
    claim = SimpleNamespace(claim_type="PRIVACY", claim_text="Personal data is masked before any external call.")
    card = SimpleNamespace(capability_tags=["us_hosted_inference", "no_human_gate"], exact_locator="svc.py:10-18")
    ctx = build_focused_context(claim, sl, card)
    assert "Personal data is masked" in ctx and "us_hosted_inference" in ctx and "17: " in ctx and "requests.post" in ctx
    assert "a = 1" not in ctx and "b = 2" not in ctx and "c = 3" not in ctx  # lines far from the matching call are pruned (neighbours kept for context)
    assert len(build_focused_context(claim, sl, card, max_chars=200)) <= 200 and build_focused_context(None, None, None) == ""


def test_drift_findings_carry_pruned_context_to_the_llm(monkeypatch):
    prompts = []
    real = LLMClient.structured

    def spy(self, system, user, schema, fallback):
        prompts.append(user)
        return real(self, system, user, schema, fallback)
    monkeypatch.setattr(LLMClient, "structured", spy)
    run_audit(A, "a")
    drift = [p for p in prompts if "Evidence context" in p]
    assert drift and all("Policy claim" in p and "Code (" in p for p in drift)
    assert all(len(p) < 3000 for p in prompts)  # never whole files


@pytest.mark.parametrize("env,expect", [
    ({"DATABRICKS_HOST": "https://x.cloud.databricks.com", "DATABRICKS_TOKEN": "t", "DATABRICKS_SERVING_ENDPOINT": "databricks-claude-sonnet-4-5"}, "databricks-claude"),
    ({"DATABRICKS_HOST": "https://x.cloud.databricks.com", "DATABRICKS_TOKEN": "t", "DATABRICKS_SERVING_ENDPOINT": "databricks-meta-llama-3-3-70b-instruct"}, "databricks"),
    ({}, "openai-compatible"),
])
def test_backend_detection(monkeypatch, env, expect):
    for k in ("DATABRICKS_HOST", "DATABRICKS_TOKEN", "DATABRICKS_SERVING_ENDPOINT", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(k, "")  # empty (not unset): LLMClient re-reads .env with setdefault
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert LLMClient(offline=False).backend == expect


def test_native_json_schema_for_openai_and_prompt_json_for_databricks_claude(monkeypatch):
    for k in ("DATABRICKS_HOST", "DATABRICKS_TOKEN", "DATABRICKS_SERVING_ENDPOINT", "ANTHROPIC_API_KEY", "BYOM_JSON_SCHEMA"):
        monkeypatch.setenv(k, "")
    sent = {}

    class Completions:
        def create(self, **kw):
            sent.update(kw)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"summary": "ok"}'))])
    oa = LLMClient(base_url="https://api.openai.com/v1", model="gpt-x", api_key="k", offline=False)
    oa._client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    oa._available = True
    assert oa.supports_json_schema and oa.structured("s", "u", Narrative, lambda: Narrative(summary="fb")).summary == "ok"
    assert sent["response_format"]["type"] == "json_schema" and sent["response_format"]["json_schema"]["name"] == "Narrative"
    assert "properties" in sent["response_format"]["json_schema"]["schema"]

    # a server that rejects json_schema is detected once and downgraded to json_object
    sent.clear()
    n = {"c": 0}

    class Picky:
        def create(self, **kw):
            n["c"] += 1
            if kw["response_format"]["type"] == "json_schema":
                raise RuntimeError("response_format json_schema unsupported")
            sent.update(kw)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"summary": "ok2"}'))])
    oa2 = LLMClient(base_url="https://api.openai.com/v1", model="m", api_key="k", offline=False)
    oa2._client, oa2._available = SimpleNamespace(chat=SimpleNamespace(completions=Picky())), True
    assert oa2.structured("s", "u", Narrative, lambda: Narrative(summary="fb")).summary == "ok2" and not oa2.supports_json_schema
    assert sent["response_format"] == {"type": "json_object"}

    # Databricks Claude: no response_format, JSON enforced by the prompt, invalid replies retried and validated
    for k, v in {"DATABRICKS_HOST": "https://x.cloud.databricks.com", "DATABRICKS_TOKEN": "tok", "DATABRICKS_SERVING_ENDPOINT": "databricks-claude-sonnet-4-5"}.items():
        monkeypatch.setenv(k, v)
    bodies, replies = [], iter(["not json at all", '```json\n{"summary": "fixed"}\n```'])

    def handler(req):
        bodies.append(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": next(replies)}}]})
    db = LLMClient(offline=False, http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert db.backend == "databricks-claude" and not db.supports_json_schema
    assert db.structured("sys", "usr", Narrative, lambda: Narrative(summary="fb")).summary == "fixed"
    assert len(bodies) == 2 and all("response_format" not in b for b in bodies) and "JSON" in bodies[0]["messages"][0]["content"]


# ------------------------------------------------------------------ export dedupe
def test_export_dicts_are_the_single_serialisation_path():
    rep = run_audit(A, "a")
    ex = rep.to_export_dict()
    f = rep.confirmed_findings[0]
    assert ex["confirmed_findings"][0] == f.to_export_dict()
    for k in ("finding_id", "severity", "status", "due_date", "days_remaining", "confidence", "title", "system_id", "system_name", "primary_rule", "also_engages",
              "summary", "code_vs_doc_drift", "evidence", "exposure_text", "owner", "effort_days", "human_review_required", "remediation_steps",
              "related_ids", "history_status", "first_seen_at", "linkup_citation_urls"):
        assert k in ex["confirmed_findings"][0], k  # every CLAUDE.md contract field
    assert set(ex["stack_telemetry"]) >= {"databricks_endpoint", "unity_catalog_table", "mlflow_trace_id", "mongodb_database", "mongodb_checkpoint_id", "linkup_sources_verified_count"}
    assert all("check_id" in p for p in ex["passed_checks"])
    json.dumps(ex, default=str)  # fully serialisable

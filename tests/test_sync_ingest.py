"""Full knowledge sync: folders (many formats), web pages, change detection, removal, SSRF guard, scheduler."""
from __future__ import annotations

import docx
import httpx
import pytest
from typer.testing import CliRunner

from src.law_sync.ingest import FolderSource, SyncConfig, UrlSource, fetch_url, load_config, run_full_sync, sync_folder, sync_remote_docs, sync_url
from src.storage import get_compliance_store

GLOBAL = "global_regulations"
PUBLIC = lambda host, port=None: [(2, 1, 6, "", ("93.184.216.34", 0))]
PRIVATE = lambda host, port=None: [(2, 1, 6, "", ("10.0.0.5", 0))]
PAGE = "<html><body><h1>Article 5 guidance</h1>" + "<p>Providers must not deploy untargeted scraping of facial images from the internet or CCTV footage to build databases.</p>" * 6 + "</body></html>"


def chunks_of(store, key=None):
    return [d for d in store._col("tenant_artifacts").find({"tenant_id": GLOBAL}) if key is None or d.get("source_key") == key]


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def test_folder_ingests_many_formats_then_skips_unchanged_updates_and_removes(tmp_path):
    store = get_compliance_store()
    (tmp_path / "a.md").write_text("# Guidance A\nHuman oversight must be effective and documented.\n")
    d = docx.Document()
    d.add_heading("Guidance B", 1)
    d.add_paragraph("Providers must keep technical documentation up to date for high-risk systems.")
    d.save(tmp_path / "b.docx")
    (tmp_path / "c.html").write_text("<h1>Guidance C</h1><p>Transparency obligations apply to AI-generated content.</p>")
    (tmp_path / ".hidden.md").write_text("# hidden\nignored\n")
    src = FolderSource(str(tmp_path), "EU_AI_ACT", "REGULATORY_DOC")

    first = {r.source.split("/")[-1]: r.status for r in sync_folder(store, src)}
    assert first == {"a.md": "new", "b.docx": "new", "c.html": "new"}
    n = len(chunks_of(store))
    assert n >= 3 and all(c["tenant_id"] == GLOBAL and c["jurisdiction"] == "EU_AI_ACT" for c in chunks_of(store))

    assert {r.status for r in sync_folder(store, src)} == {"unchanged"}
    assert len(chunks_of(store)) == n  # nothing re-embedded or duplicated

    (tmp_path / "a.md").write_text("# Guidance A\nRevised: oversight must be effective, documented and tested.\n")
    again = {r.source.split("/")[-1]: r.status for r in sync_folder(store, src)}
    assert again["a.md"] == "updated" and again["b.docx"] == "unchanged"
    texts = " ".join(c["text"] for c in chunks_of(store))
    assert "Revised" in texts and "documented and tested" in texts
    assert sum("Human oversight must be effective and documented." in c["text"] for c in chunks_of(store)) == 0  # stale passage replaced

    (tmp_path / "c.html").unlink()
    gone = [r for r in sync_folder(store, src) if r.status == "removed"]
    assert len(gone) == 1 and not any("Transparency obligations" in c["text"] for c in chunks_of(store))


def test_missing_folder_is_an_error_not_a_crash():
    r = sync_folder(get_compliance_store(), FolderSource("/no/such/dir"))
    assert r[0].status == "error"


def test_url_ingest_change_detection_and_citation_fields():
    store = get_compliance_store()
    body = {"v": PAGE}
    c = client_for(lambda req: httpx.Response(200, text=body["v"], headers={"content-type": "text/html; charset=utf-8"}))
    src = UrlSource("https://example.org/ai-act/article-5", "EU_AI_ACT")
    assert sync_url(store, src, c, PUBLIC).status == "new"
    assert sync_url(store, src, c, PUBLIC).status == "unchanged"
    row = chunks_of(store, "url:https://example.org/ai-act/article-5")[0]
    assert row["source_url"] == "https://example.org/ai-act/article-5" and row["fetched_at"] and row["exact_locator"]
    body["v"] = PAGE.replace("untargeted scraping", "indiscriminate scraping")
    assert sync_url(store, src, c, PUBLIC).status == "updated"
    assert not any("untargeted scraping" in d["text"] for d in chunks_of(store, "url:https://example.org/ai-act/article-5"))


def test_blocked_or_empty_pages_are_errors_not_indexed():
    store = get_compliance_store()
    c = client_for(lambda req: httpx.Response(200, text="<html><body>Checking your browser...</body></html>", headers={"content-type": "text/html"}))
    r = sync_url(store, UrlSource("https://eur-lex.example/x"), c, PUBLIC)
    assert r.status == "error" and "almost no text" in r.detail and chunks_of(store) == []
    c403 = client_for(lambda req: httpx.Response(403))
    assert sync_url(store, UrlSource("https://eur-lex.example/y"), c403, PUBLIC).status == "error"


@pytest.mark.parametrize("url,resolver", [("http://example.org/x", PUBLIC), ("https://user:pw@example.org/x", PUBLIC), ("https://intranet.example/x", PRIVATE)])
def test_ssrf_guard(url, resolver):
    with pytest.raises(ValueError):
        fetch_url(url, client_for(lambda r: httpx.Response(200, text="x")), resolver)


def test_redirect_to_private_host_is_refused():
    def handler(req):
        if req.url.host == "example.org":
            return httpx.Response(302, headers={"location": "https://internal.example/secret"})
        return httpx.Response(200, text="secret")
    resolver = lambda host, port=None: PRIVATE(host) if host == "internal.example" else PUBLIC(host)
    with pytest.raises(ValueError, match="not a public address"):
        fetch_url("https://example.org/start", client_for(handler), resolver)


def test_pdf_url_is_chunked_with_url_citation(tmp_path):
    from weasyprint import HTML
    HTML(string="<h1>Article 14</h1><p>" + "Human oversight measures must allow natural persons to intervene. " * 12 + "</p>").write_pdf(str(tmp_path / "t.pdf"))
    raw = (tmp_path / "t.pdf").read_bytes()
    store = get_compliance_store()
    c = client_for(lambda req: httpx.Response(200, content=raw, headers={"content-type": "application/pdf"}))
    r = sync_url(store, UrlSource("https://example.org/files/art14.pdf", "EU_AI_ACT", "REGULATORY_PDF"), c, PUBLIC)
    assert r.status == "new" and r.chunks >= 1
    row = chunks_of(store, "url:https://example.org/files/art14.pdf")[0]
    assert row["source_url"].endswith("art14.pdf") and "example.org/files/art14.pdf" in row["filename"]


def test_remote_docs_refuse_global_tenant():
    assert sync_remote_docs(get_compliance_store(), GLOBAL)[0].status == "error"


def test_config_file_relative_paths(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "s.yaml").write_text("folders:\n  - path: docs\n    jurisdiction: EU_GDPR\nurls:\n  - url: https://example.org/a\nremote_docs_tenant: acme\n")
    cfg = load_config(tmp_path / "s.yaml")
    assert cfg.folders[0].path == str((tmp_path / "docs").resolve()) and cfg.folders[0].jurisdiction == "EU_GDPR"
    assert cfg.urls[0].jurisdiction == "EU_AI_ACT" and cfg.remote_docs_tenant == "acme"
    assert load_config(tmp_path / "missing.yaml") == SyncConfig()


def test_full_sync_runs_rules_folders_and_reports_errors(tmp_path):
    (tmp_path / "g.md").write_text("# Guide\nControllers must document an Article 9 condition for special-category data.\n")
    cfg = SyncConfig(folders=[FolderSource(str(tmp_path), "EU_GDPR")], urls=[UrlSource("http://insecure.example/x")])
    rep = run_full_sync(cfg, deep_linkup=False, resolver=PUBLIC)
    assert rep.rules_total >= 20 and rep.rules_version
    assert {s.status for s in rep.sources} == {"new", "error"} and len(rep.errors) == 1
    assert all(s.status == "unchanged" for s in run_full_sync(SyncConfig(folders=cfg.folders), deep_linkup=False).sources)


def test_cli_sync_laws_with_folder_and_exit_code(tmp_path):
    from aegis_audit.cli import app
    (tmp_path / "n.md").write_text("# Note\nRecord-keeping obligations require automatic event logs.\n")
    ok = CliRunner().invoke(app, ["sync-laws", "--no-deep-linkup", "--folder", str(tmp_path)])
    assert ok.exit_code == 0 and "n.md" in ok.output and "new" in ok.output
    bad = CliRunner().invoke(app, ["sync-laws", "--no-deep-linkup", "--folder", str(tmp_path / "missing")])
    assert bad.exit_code == 1 and "error" in bad.output


def test_scheduler_runs_full_sync_and_survives_failures(monkeypatch):
    from src.law_sync import scheduler
    called = []
    monkeypatch.setattr("src.law_sync.ingest.run_full_sync", lambda *a, **k: called.append(1) or (_ for _ in ()).throw(RuntimeError("boom")))
    scheduler.scheduled_full_sync()  # must not raise
    assert called == [1]
    sch = scheduler.start_scheduler(24)
    try:
        assert sch.get_job(scheduler.JOB_ID).func is scheduler.scheduled_full_sync
    finally:
        scheduler.stop_scheduler()
